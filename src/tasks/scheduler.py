from __future__ import annotations

from celery import shared_task
from django.db import connection, transaction
from django.utils import timezone


_DUE_SQL = """
SELECT id
FROM feeds_feed
WHERE next_fetch_at <= now()
  AND is_active
  AND NOT is_deleted
  AND (disabled_until IS NULL OR disabled_until <= now())
ORDER BY next_fetch_at
FOR UPDATE SKIP LOCKED
LIMIT %(limit)s;
"""


@shared_task(name="tasks.scheduler.enqueue_due_feeds")
def enqueue_due_feeds(limit: int = 200) -> dict:
    from tasks.fetcher import fetch_feed

    enqueued: list[int] = []
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(_DUE_SQL, {"limit": limit})
        ids = [row[0] for row in cur.fetchall()]
        if ids:
            now = timezone.now()
            cur.execute(
                "UPDATE feeds_feed "
                "SET next_fetch_at = now() + (interval_seconds || ' seconds')::interval "
                "WHERE id = ANY(%(ids)s);",
                {"ids": ids},
            )
            for fid in ids:
                fetch_feed.apply_async(args=[fid])
                enqueued.append(fid)
            _ = now
    return {"enqueued": len(enqueued)}


@shared_task(name="tasks.scheduler.refresh_robots_cache")
def refresh_robots_cache() -> dict:
    """Walk active feeds and warm robots cache for each domain (lazy)."""
    from urllib.parse import urlparse

    from apps.feeds.models import Feed
    from apps.feeds.robots import invalidate

    domains: set[str] = set()
    for url in Feed.objects.filter(is_active=True, is_deleted=False).values_list("url", flat=True):
        host = urlparse(url).hostname
        if host:
            domains.add(host.lower())
    for d in domains:
        invalidate(d)
    return {"invalidated": len(domains)}


@shared_task(name="tasks.scheduler.cleanup_old_articles")
def cleanup_old_articles(days: int = 365) -> dict:
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(days=days)
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE articles_article SET is_deleted = true "
            "WHERE NOT is_deleted AND published_at IS NOT NULL AND published_at < %(c)s;",
            {"c": cutoff},
        )
        affected = cur.rowcount
    return {"soft_deleted": affected}
