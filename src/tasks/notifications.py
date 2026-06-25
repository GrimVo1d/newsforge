"""Webhook (HMAC) + email delivery for matched subscriptions."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import smtplib
import time
from datetime import timedelta
from typing import Any

import httpx
from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from apps.articles.models import Article
from apps.core import safe_http
from apps.subscriptions.models import DeliveryLog, Subscription

logger = logging.getLogger(__name__)

MAX_SUBJECT_CHARS = 200
MAX_ERROR_CHARS = 1000
# Longer than any single attempt (webhook timeout 10 s, SMTP) and shorter than the retries.
LEASE = timedelta(minutes=2)


class RetryableDeliveryError(Exception):
    """The receiver answered with a status worth retrying (5xx, 408, 429)."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"receiver answered {status_code}")
        self.status_code = status_code


class DeliveryInFlightError(Exception):
    """Another task is sending this pair right now; retry after its lease ends."""


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


def _claim(subscription_id: int, article_id: int) -> bool:
    """Take the send lease for a pair; False when it was delivered already."""
    now = timezone.now()
    with transaction.atomic():
        log, _ = DeliveryLog.objects.select_for_update().get_or_create(
            subscription_id=subscription_id,
            article_id=article_id,
            defaults={"succeeded": False, "attempts": 0},
        )
        if log.succeeded:
            return False
        if log.leased_until is not None and log.leased_until > now:
            raise DeliveryInFlightError(f"{subscription_id}:{article_id}")
        DeliveryLog.objects.filter(pk=log.pk).update(leased_until=now + LEASE)
    return True


def _record(
    subscription_id: int,
    article_id: int,
    *,
    succeeded: bool,
    http_status: int | None,
    error: str | None,
) -> None:
    """Log an attempt and release the lease. A delivered pair is never marked failed again."""
    values: dict[str, Any] = {
        "http_status": http_status,
        "error": error[:MAX_ERROR_CHARS] if error else None,
        "leased_until": None,
    }
    if succeeded:
        values["succeeded"] = True
    DeliveryLog.objects.filter(
        subscription_id=subscription_id, article_id=article_id, succeeded=False
    ).update(**values, attempts=F("attempts") + 1, delivered_at=timezone.now())


def _failure(exc: Exception) -> str:
    """Name a failed attempt for the delivery log without the receiver's or mail server's text.

    The log is visible to the subscription owner, so it gets a category; details go to our logs.
    """
    if isinstance(exc, RetryableDeliveryError):
        return str(exc)
    if isinstance(exc, (httpx.TimeoutException, safe_http.DeadlineExceededError, TimeoutError)):
        return "timeout"
    if isinstance(exc, httpx.HTTPError):
        return "connection failed"
    if isinstance(exc, smtplib.SMTPException):
        return "mail server unavailable"
    if isinstance(exc, OSError):
        return "connection failed"
    return "internal error"


def _send_webhook(sub: Subscription, body: bytes, idempotency_key: str) -> int:
    timestamp = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": settings.USER_AGENT,
        "X-NF-Timestamp": str(timestamp),
        "X-NF-Signature": sign(sub.webhook_secret or "", timestamp, body),  # checked in deliver
        "X-Idempotency-Key": idempotency_key,
    }
    resp = safe_http.request(
        "POST",
        sub.webhook_url or "",
        headers=headers,
        content=body,
        timeout=10.0,
        max_redirects=0,
        allow_http=settings.ALLOW_PLAIN_HTTP,
        discard_body=True,  # only the status matters; a broken body must not fail a delivery
    )
    if resp.status_code >= 500 or resp.status_code in (408, 429):
        raise RetryableDeliveryError(resp.status_code)
    return resp.status_code


def _send_email(sub: Subscription, article: Article) -> int:
    """Send the mail; return the SMTP code of a final answer, raise for one worth retrying.

    A refused recipient (5xx) or refused message is final; temporary (4xx) answers,
    connection problems and our own configuration errors (authentication, sender) are retried.
    """
    try:
        send_mail(
            subject=_subject(article.title),
            message=article.url,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[sub.email_to or ""],
            fail_silently=False,
        )
    except smtplib.SMTPRecipientsRefused as exc:
        codes = [code for code, _ in exc.recipients.values()]
        if codes and all(code >= 500 for code in codes):
            return int(codes[0])
        raise
    except smtplib.SMTPDataError as exc:
        if exc.smtp_code >= 500:
            return int(exc.smtp_code)
        raise
    return 250


@shared_task(
    name="tasks.notifications.deliver",
    acks_late=True,
    autoretry_for=(
        httpx.HTTPError,
        safe_http.DeadlineExceededError,
        RetryableDeliveryError,
        DeliveryInFlightError,
        OSError,  # includes smtplib.SMTPException
    ),
    retry_backoff=30,
    retry_jitter=True,
    max_retries=5,
)
def deliver(subscription_id: int, article_id: int) -> dict[str, Any]:
    sub = Subscription.objects.filter(pk=subscription_id, is_active=True).first()
    article = Article.objects.filter(
        pk=article_id, is_deleted=False, feed__is_deleted=False
    ).first()
    if sub is None or article is None:
        # Paused or deleted meanwhile: nothing to send, nothing to retry.
        return {"status": None, "error": "gone"}

    if not _claim(subscription_id, article_id):
        return {"deduped": True}

    try:
        if sub.delivery == Subscription.Delivery.WEBHOOK and sub.webhook_url:
            if not sub.webhook_secret:
                # Signed with an empty key, the payload could be forged by anyone; the API
                # always issues a secret, so this is a row made by hand.
                _record(sub.id, article.id, succeeded=False, http_status=None, error="no secret")
                return {"status": None, "error": "no secret"}
            body = json.dumps(_payload(article), separators=(",", ":")).encode()
            status = _send_webhook(sub, body, _idempotency_key(subscription_id, article_id))
        elif sub.delivery == Subscription.Delivery.EMAIL and sub.email_to:
            status = _send_email(sub, article)
        else:
            _record(sub.id, article.id, succeeded=False, http_status=None, error="no target")
            return {"status": None, "error": "no target"}
    except safe_http.UnsafeURLError as exc:
        _record(sub.id, article.id, succeeded=False, http_status=None, error=f"blocked: {exc}")
        return {"status": None, "error": "blocked"}
    except Exception as exc:
        # Log the failed attempt, then let autoretry_for decide whether to try again.
        status_code = exc.status_code if isinstance(exc, RetryableDeliveryError) else None
        logger.warning("delivery %s/%s failed: %r", subscription_id, article_id, exc)
        _record(sub.id, article.id, succeeded=False, http_status=status_code, error=_failure(exc))
        raise

    # Redirects are not followed, so a 3xx answer means the payload did not arrive.
    ok = 200 <= status < 300  # SMTP "250 OK" for email falls in the same range
    _record(
        sub.id,
        article.id,
        succeeded=ok,
        http_status=status,
        error=None if ok else f"receiver answered {status}",
    )
    if ok and sub.interval == Subscription.Interval.INSTANT:
        # The digest tracks its own window; instant subscriptions only report the last send.
        Subscription.objects.filter(pk=sub.id, interval=sub.interval).update(
            last_notified_at=timezone.now()
        )
    return {"status": status, "succeeded": ok}


_MATCH_INSTANT_SQL = """
SELECT s.id
FROM subscriptions_subscription s
JOIN articles_article a ON a.id = %(aid)s AND NOT a.is_deleted
JOIN feeds_feed f ON f.id = a.feed_id AND NOT f.is_deleted
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
        deliver.apply_async(args=(sid, article_id))
    return {"fanout": len(ids)}
