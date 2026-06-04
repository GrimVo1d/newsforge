from __future__ import annotations

from typing import Any

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
def enqueue_due_feeds(limit: int = 200) -> dict[str, Any]:
    from tasks.fetcher import fetch_feed

    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(_DUE_SQL, {"limit": limit})
        ids = [row[0] for row in cur.fetchall()]
        if ids:
            cur.execute(
                "UPDATE feeds_feed "
                "SET next_fetch_at = now() + (interval_seconds || ' seconds')::interval "
                "WHERE id = ANY(%(ids)s);",
                {"ids": ids},
            )
    # Queue after commit, so a fast worker never sees the old next_fetch_at.
    for fid in ids:
        fetch_feed.apply_async(args=(fid,))
    return {"enqueued": len(ids)}


@shared_task(name="tasks.scheduler.refresh_robots_cache")
def refresh_robots_cache() -> dict[str, Any]:
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
def cleanup_old_articles(days: int = 365) -> dict[str, Any]:
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
