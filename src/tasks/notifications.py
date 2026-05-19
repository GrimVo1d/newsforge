"""Webhook (HMAC) + email delivery for matched subscriptions."""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx
from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction

from apps.articles.models import Article
from apps.subscriptions.models import DeliveryLog, Subscription


def _signature(secret_hash: str, payload: bytes) -> str:
    # Use the stored hash as the HMAC key — receivers verify against the plaintext
    # they hold (using the same algorithm). We document this in ADR-0005.
    return hmac.new(secret_hash.encode(), payload, hashlib.sha256).hexdigest()


def _idempotency_key(subscription_id: int, article_id: int) -> str:
    return hashlib.sha256(f"{subscription_id}:{article_id}".encode()).hexdigest()


def _payload(article: Article) -> dict:
    return {
        "id": article.id,
        "title": article.title,
        "url": article.url,
        "summary": article.summary,
        "feed_id": article.feed_id,
        "published_at": article.published_at.isoformat() if article.published_at else None,
    }


@shared_task(name="tasks.notifications.deliver", acks_late=True, autoretry_for=(httpx.HTTPError,),
             retry_backoff=30, retry_jitter=True, max_retries=5)
def deliver(subscription_id: int, article_id: int) -> dict:
    sub = Subscription.objects.get(pk=subscription_id, is_active=True)
    article = Article.objects.get(pk=article_id, is_deleted=False)

    payload = _payload(article)
    body = json.dumps(payload, separators=(",", ":")).encode()
    idk = _idempotency_key(subscription_id, article_id)
    http_status: int | None = None
    error: str | None = None

    if sub.delivery == Subscription.Delivery.WEBHOOK and sub.webhook_url:
        sig = _signature(sub.webhook_secret or "", body)
        headers = {
            "Content-Type": "application/json",
            "X-NF-Signature": sig,
            "X-Idempotency-Key": idk,
            "User-Agent": settings.USER_AGENT,
        }
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(sub.webhook_url, content=body, headers=headers)
            http_status = resp.status_code
        except httpx.HTTPError as exc:
            error = str(exc)
            raise
    elif sub.delivery == Subscription.Delivery.EMAIL and sub.email_to:
        send_mail(
            subject=f"[newsforge] {article.title}",
            message=article.url,
            from_email=settings.DEFAULT_FROM_EMAIL if hasattr(settings, "DEFAULT_FROM_EMAIL") else "no-reply@newsforge.local",
            recipient_list=[sub.email_to],
            fail_silently=False,
        )
        http_status = 200
    else:
        error = "no delivery target"

    try:
        with transaction.atomic():
            DeliveryLog.objects.create(
                subscription_id=subscription_id,
                article_id=article_id,
                http_status=http_status,
                error=error,
            )
    except IntegrityError:
        # Duplicate delivery — already logged, treat as success.
        return {"deduped": True}
    return {"status": http_status, "error": error}


@shared_task(name="tasks.notifications.fanout_instant", acks_late=True)
def fanout_instant(article_id: int) -> dict:
    """Find instant-interval subscriptions whose query matches this article."""
    from django.db import connection

    sql = """
    SELECT s.id FROM subscriptions_subscription s, articles_article a,
         websearch_to_tsquery(coalesce(a.language,'simple')::regconfig, unaccent(s.q)) AS tsq
    WHERE s.is_active
      AND s.interval = 'instant'
      AND a.id = %(aid)s
      AND a.tsv @@ tsq
      AND (cardinality(s.feeds) = 0 OR a.feed_id = ANY(s.feeds));
    """
    with connection.cursor() as cur:
        cur.execute(sql, {"aid": article_id})
        ids = [r[0] for r in cur.fetchall()]
    for sid in ids:
        deliver.apply_async(args=[sid, article_id])
    return {"fanout": len(ids)}
