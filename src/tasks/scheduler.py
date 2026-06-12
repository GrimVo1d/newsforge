from __future__ import annotations

import time
from typing import Any

from celery import shared_task
from django.db import connection, transaction
from django.utils import timezone

_DUE_SQL = """
SELECT id, interval_seconds
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
        due = cur.fetchall()
        ids = [row[0] for row in due]
        if ids:
            cur.execute(
                "UPDATE feeds_feed "
                "SET next_fetch_at = now() + (interval_seconds || ' seconds')::interval "
                "WHERE id = ANY(%(ids)s);",
                {"ids": ids},
            )
    # Queue after commit, so a fast worker never sees the old next_fetch_at. A task still
    # queued when the next round is due is dropped, so a backlog does not pile up duplicates.
    for fid, interval in due:
        fetch_feed.apply_async(args=(fid,), expires=interval)
    return {"enqueued": len(ids)}


@shared_task(name="tasks.scheduler.refresh_robots_cache")
def refresh_robots_cache() -> dict[str, Any]:
    """Drop the cached robots.txt of every active feed's host; the next fetch reloads it."""
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


CLEANUP_BATCH = 5_000
CLEANUP_BUDGET_SECONDS = 240

_CLEANUP_SQL = """
UPDATE articles_article SET is_deleted = true
WHERE id IN (
    SELECT id FROM articles_article
    WHERE NOT is_deleted AND coalesce(published_at, created_at) < %(c)s
    LIMIT %(batch)s
);
"""


@shared_task(
    name="tasks.scheduler.cleanup_old_articles",
    soft_time_limit=CLEANUP_BUDGET_SECONDS + 60,
    time_limit=CLEANUP_BUDGET_SECONDS + 120,
)
def cleanup_old_articles(days: int = 365) -> dict[str, Any]:
    """Soft-delete old articles in short batches, so no statement holds many row locks.

    Articles without a date count from when they were stored. Whatever is left after the
    time budget is handled by the next run.
    """
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(days=days)
    stop_at = time.monotonic() + CLEANUP_BUDGET_SECONDS
    affected = 0
    while time.monotonic() < stop_at:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(_CLEANUP_SQL, {"c": cutoff, "batch": CLEANUP_BATCH})
            batch = cur.rowcount
        affected += batch
        if batch < CLEANUP_BATCH:
            break
    return {"soft_deleted": affected}
