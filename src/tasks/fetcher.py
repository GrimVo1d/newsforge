"""Celery task: fetch a single feed, parse, fan out to process_article."""

from __future__ import annotations

from datetime import datetime, timezone

import feedparser
from celery import shared_task
from django.utils import timezone as djtz

from apps.feeds.fetcher import fetch
from apps.feeds.models import Feed, FeedStatus
from apps.feeds.ratelimit import try_acquire
from apps.feeds.robots import is_allowed


def _entry_published(entry: dict) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)


@shared_task(name="tasks.fetcher.fetch_feed", acks_late=True, bind=True)
def fetch_feed(self, feed_id: int) -> dict:  # type: ignore[no-untyped-def]
    feed = Feed.objects.get(pk=feed_id, is_deleted=False, is_active=True)

    if not is_allowed(feed.url):
        feed.last_status = FeedStatus.ROBOTS_BLOCKED
        feed.last_fetched_at = djtz.now()
        feed.save(update_fields=["last_status", "last_fetched_at", "updated_at"])
        return {"status": FeedStatus.ROBOTS_BLOCKED}

    if not try_acquire(feed.url):
        return {"status": "rate_limited"}

    result = fetch(feed.url, etag=feed.etag, last_modified=feed.last_modified)
    feed.last_fetched_at = djtz.now()

    if result.status == "not_modified":
        feed.last_status = FeedStatus.NOT_MODIFIED
        feed.consecutive_errors = 0
        feed.save(
            update_fields=["last_status", "last_fetched_at", "consecutive_errors", "updated_at"]
        )
        return {"status": FeedStatus.NOT_MODIFIED}

    if result.status != "ok" or result.body is None:
        feed.last_status = result.status
        feed.consecutive_errors = feed.consecutive_errors + 1
        feed.save(
            update_fields=["last_status", "last_fetched_at", "consecutive_errors", "updated_at"]
        )
        return {"status": result.status}

    parsed = feedparser.parse(result.body)
    entries = list(parsed.entries or [])

    from tasks.articles import process_article  # local import to avoid celery circular

    for entry in entries:
        process_article.apply_async(
            kwargs={
                "feed_id": feed.id,
                "url": entry.get("link") or "",
                "title": entry.get("title") or "",
                "summary": entry.get("summary") or "",
                "body": entry.get("content", [{}])[0].get("value", "") if entry.get("content") else "",
                "guid": entry.get("id") or entry.get("guid") or "",
                "author": entry.get("author"),
                "published_at": (_entry_published(entry).isoformat()
                                 if _entry_published(entry) else None),
            }
        )

    feed.etag = result.etag or feed.etag
    feed.last_modified = result.last_modified or feed.last_modified
    feed.last_status = FeedStatus.OK
    feed.consecutive_errors = 0
    feed.save(
        update_fields=[
            "etag",
            "last_modified",
            "last_status",
            "last_fetched_at",
            "consecutive_errors",
            "updated_at",
        ]
    )
    return {"status": FeedStatus.OK, "entries": len(entries)}
