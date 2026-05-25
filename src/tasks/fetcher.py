"""Celery task: fetch a single feed, parse, fan out to process_article."""

from __future__ import annotations

from datetime import UTC, datetime

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
    return datetime(*parsed[:6], tzinfo=UTC)


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
        from apps.feeds.backoff import disabled_until, next_attempt_at, should_disable

        feed.last_status = result.status
        feed.consecutive_errors = feed.consecutive_errors + 1
        feed.next_fetch_at = next_attempt_at(
            base_seconds=feed.interval_seconds,
            consecutive_errors=feed.consecutive_errors,
        )
        if should_disable(feed.consecutive_errors):
            feed.disabled_until = disabled_until()
        feed.save(
            update_fields=[
                "last_status",
                "last_fetched_at",
                "consecutive_errors",
                "next_fetch_at",
                "disabled_until",
                "updated_at",
            ]
        )
        return {"status": result.status}

    body = result.body
    if body[:3] == b"\xef\xbb\xbf":  # strip UTF-8 BOM that some servers send
        body = body[3:]
    parsed = feedparser.parse(body)
    entries = list(parsed.entries or [])

    from tasks.articles import process_article  # local import to avoid celery circular

    for entry in entries:
        content = entry.get("content") or []
        body_html = content[0].get("value", "") if content else ""
        published = _entry_published(entry)
        process_article.apply_async(
            kwargs={
                "feed_id": feed.id,
                "url": entry.get("link") or "",
                "title": entry.get("title") or "",
                "summary": entry.get("summary") or "",
                "body": body_html,
                "guid": entry.get("id") or entry.get("guid") or "",
                "author": entry.get("author"),
                "published_at": published.isoformat() if published else None,
            }
        )

    feed.etag = result.etag or feed.etag
    feed.last_modified = result.last_modified or feed.last_modified
    feed.last_status = FeedStatus.OK
    feed.consecutive_errors = 0
    feed.disabled_until = None
    feed.save(
        update_fields=[
            "etag",
            "last_modified",
            "last_status",
            "last_fetched_at",
            "consecutive_errors",
            "disabled_until",
            "updated_at",
        ]
    )
    return {"status": FeedStatus.OK, "entries": len(entries)}
