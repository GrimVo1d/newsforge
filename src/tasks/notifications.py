"""Webhook (HMAC) + email delivery for matched subscriptions."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx
from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import connection, transaction
from django.db.models import F

from apps.articles.models import Article
from apps.core import safe_http
from apps.subscriptions.models import DeliveryLog, Subscription

MAX_SUBJECT_CHARS = 200
MAX_ERROR_CHARS = 1000


class RetryableDeliveryError(Exception):
    """The receiver answered with a status worth retrying (5xx, 408, 429)."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"receiver answered {status_code}")
        self.status_code = status_code


def sign(secret: str, timestamp: int, body: bytes) -> str:
    """Signature sent in X-NF-Signature: HMAC-SHA256 over ``"<timestamp>." + body``."""
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def _idempotency_key(subscription_id: int, article_id: int) -> str:
    return hashlib.sha256(f"{subscription_id}:{article_id}".encode()).hexdigest()


def _payload(article: Article) -> dict[str, Any]:
    return {
        "id": article.id,
        "title": article.title,
        "url": article.url,
        "summary": article.summary,
        "feed_id": article.feed_id,
        "published_at": article.published_at.isoformat() if article.published_at else None,
    }


def _subject(title: str) -> str:
    # Header injection guard: collapse all whitespace, including CR/LF.
    return f"[newsforge] {' '.join(title.split())}"[:MAX_SUBJECT_CHARS]


def _record(
    subscription_id: int,
    article_id: int,
    *,
    succeeded: bool,
    http_status: int | None,
    error: str | None,
) -> None:
    values = {
        "succeeded": succeeded,
        "http_status": http_status,
        "error": error[:MAX_ERROR_CHARS] if error else None,
    }
    with transaction.atomic():
        log, created = DeliveryLog.objects.select_for_update().get_or_create(
            subscription_id=subscription_id, article_id=article_id, defaults=values
        )
        if not created:
            DeliveryLog.objects.filter(pk=log.pk).update(**values, attempts=F("attempts") + 1)


def _send_webhook(sub: Subscription, body: bytes, idempotency_key: str) -> int:
    timestamp = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": settings.USER_AGENT,
        "X-NF-Timestamp": str(timestamp),
        "X-NF-Signature": sign(sub.webhook_secret or "", timestamp, body),
        "X-Idempotency-Key": idempotency_key,
    }
    resp = safe_http.request(
        "POST",
        sub.webhook_url or "",
        headers=headers,
        content=body,
        timeout=10.0,
        max_bytes=64 * 1024,
        max_redirects=0,
        allow_http=settings.ALLOW_PLAIN_HTTP,
        truncate=True,
    )
    if resp.status_code >= 500 or resp.status_code in (408, 429):
        raise RetryableDeliveryError(resp.status_code)
    return resp.status_code


@shared_task(
    name="tasks.notifications.deliver",
    acks_late=True,
    autoretry_for=(
        httpx.HTTPError,
        safe_http.DeadlineExceededError,
        RetryableDeliveryError,
        OSError,  # includes smtplib.SMTPException
    ),
    retry_backoff=30,
    retry_jitter=True,
    max_retries=5,
)
def deliver(subscription_id: int, article_id: int) -> dict[str, Any]:
    if DeliveryLog.objects.filter(
        subscription_id=subscription_id, article_id=article_id, succeeded=True
    ).exists():
        return {"deduped": True}

    sub = Subscription.objects.get(pk=subscription_id, is_active=True)
    article = Article.objects.get(pk=article_id, is_deleted=False)

    try:
        if sub.delivery == Subscription.Delivery.WEBHOOK and sub.webhook_url:
            body = json.dumps(_payload(article), separators=(",", ":")).encode()
            status = _send_webhook(sub, body, _idempotency_key(subscription_id, article_id))
        elif sub.delivery == Subscription.Delivery.EMAIL and sub.email_to:
            send_mail(
                subject=_subject(article.title),
                message=article.url,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[sub.email_to],
                fail_silently=False,
            )
            status = 250
        else:
            _record(sub.id, article.id, succeeded=False, http_status=None, error="no target")
            return {"status": None, "error": "no target"}
    except safe_http.UnsafeURLError as exc:
        _record(sub.id, article.id, succeeded=False, http_status=None, error=f"blocked: {exc}")
        return {"status": None, "error": "blocked"}
    except Exception as exc:
        # Log the failed attempt, then let autoretry_for decide whether to try again.
        status_code = exc.status_code if isinstance(exc, RetryableDeliveryError) else None
        _record(sub.id, article.id, succeeded=False, http_status=status_code, error=repr(exc))
        raise

    ok = status < 400
    _record(
        sub.id,
        article.id,
        succeeded=ok,
        http_status=status,
        error=None if ok else f"receiver answered {status}",
    )
    return {"status": status, "succeeded": ok}


_MATCH_INSTANT_SQL = """
SELECT s.id
FROM subscriptions_subscription s
JOIN articles_article a ON a.id = %(aid)s
WHERE s.is_active
  AND s.interval = 'instant'
  AND a.tsv @@ websearch_to_tsquery(a.language::regconfig, unaccent(s.q))
  AND (cardinality(s.feeds) = 0 OR a.feed_id = ANY(s.feeds))
  AND (
    cardinality(s.tag_ids) = 0
    OR EXISTS (
      SELECT 1 FROM tags_articletag t WHERE t.article_id = a.id AND t.tag_id = ANY(s.tag_ids)
    )
  );
"""


@shared_task(name="tasks.notifications.fanout_instant", acks_late=True)
def fanout_instant(article_id: int) -> dict[str, int]:
    """Queue deliveries for instant subscriptions whose query and filters match the article.

    Runs after ``apply_tag_rules`` (see ``apps.articles.receivers``) so tag filters see the
    article's tags.
    """
    with connection.cursor() as cur:
        cur.execute(_MATCH_INSTANT_SQL, {"aid": article_id})
        ids = [r[0] for r in cur.fetchall()]
    for sid in ids:
        deliver.apply_async(args=[sid, article_id])
    return {"fanout": len(ids)}
