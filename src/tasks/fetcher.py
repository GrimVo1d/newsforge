"""Celery task: fetch a single feed, parse, fan out to process_article."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urljoin

import feedparser
from celery import shared_task
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone as djtz

from apps.articles.normalizer import plain_text
from apps.core.safe_http import UnsafeURLError, canonical_url
from apps.feeds.backoff import disabled_until, next_attempt_at, should_disable
from apps.feeds.fetcher import FetchResult, fetch
from apps.feeds.models import MAX_URL_CHARS, Feed, FeedStatus
from apps.feeds.ratelimit import try_acquire
from apps.feeds.robots import is_allowed

UTF8_BOM = b"\xef\xbb\xbf"


def _entry_published(entry: Any) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        year, month, day, hour, minute, second = parsed[:6]
        # A leap second (":60") is stored as the last second of that minute.
        return datetime(year, month, day, hour, minute, min(second, 59), tzinfo=UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def _record_failure(feed: Feed, status: str) -> dict[str, Any]:
    feed.last_status = status
    feed.consecutive_errors += 1
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
    return {"status": status}


def _follow_permanent_redirect(feed: Feed, result: FetchResult) -> list[str]:
    """Move the feed to the target of a permanent redirect, unless another feed has it."""
    if not result.permanent_url:
        return []
    try:
        new_url = canonical_url(result.permanent_url)
    except UnsafeURLError:
        return []
    if (
        new_url == feed.url
        or len(new_url) > MAX_URL_CHARS
        or Feed.objects.filter(url=new_url).exists()
    ):
        return []
    feed.url = new_url
    return ["url"]


def _save(feed: Feed, fields: list[str]) -> None:
    try:
        with transaction.atomic():
            feed.save(update_fields=fields)
    except IntegrityError:
        if "url" not in fields:
            raise
        # Another feed moved to the same URL concurrently: this one stays where it was.
        feed.url = Feed.objects.values_list("url", flat=True).get(pk=feed.pk)
        feed.save(update_fields=[name for name in fields if name != "url"])


@shared_task(name="tasks.fetcher.fetch_feed", acks_late=True)
def fetch_feed(feed_id: int) -> dict[str, Any]:
    feed = Feed.objects.filter(pk=feed_id, is_deleted=False, is_active=True).first()
    if feed is None:
        return {"status": "gone"}

    if not is_allowed(feed.url):
        feed.last_status = FeedStatus.ROBOTS_BLOCKED
        feed.last_fetched_at = djtz.now()
        feed.save(update_fields=["last_status", "last_fetched_at", "updated_at"])
        return {"status": FeedStatus.ROBOTS_BLOCKED}

    if not try_acquire(feed.url):
        # Another feed on this host was fetched just now: retry soon, not after a full interval.
        delay = settings.PER_DOMAIN_MIN_INTERVAL * random.uniform(1, 2)
        feed.next_fetch_at = djtz.now() + timedelta(seconds=delay)
        feed.save(update_fields=["next_fetch_at", "updated_at"])
        return {"status": "rate_limited"}

    result = fetch(feed.url, etag=feed.etag, last_modified=feed.last_modified)
    feed.last_fetched_at = djtz.now()

    if result.status == "not_modified":
        moved = _follow_permanent_redirect(feed, result)
        feed.last_status = FeedStatus.NOT_MODIFIED
        feed.consecutive_errors = 0
        feed.disabled_until = None
        _save(
            feed,
            [
                *moved,
                "last_status",
                "last_fetched_at",
                "consecutive_errors",
                "disabled_until",
                "updated_at",
            ],
        )
        return {"status": FeedStatus.NOT_MODIFIED}

    if result.status != "ok" or result.body is None:
        return _record_failure(feed, result.status)

    body = result.body.removeprefix(UTF8_BOM)  # some servers send a BOM
    # The HTTP charset decides the encoding. No base URL is passed: feedparser would resolve
    # relative guids too and change the dedup key; entry links are resolved below instead.
    headers = {"content-type": result.content_type} if result.content_type else {}
    parsed = feedparser.parse(body, response_headers=headers)
    base_url = result.url or feed.url
    entries = list(parsed.entries or [])
    if parsed.bozo and not entries:
        return _record_failure(feed, FeedStatus.PARSE_ERROR)

    from tasks.articles import process_article  # local import to avoid celery circular

    for entry in entries[: settings.MAX_ENTRIES_PER_FETCH]:
        content = entry.get("content") or []
        body_html = content[0].get("value", "") if content else ""
        published = _entry_published(entry)
        link = entry.get("link") or ""
        process_article.apply_async(
            kwargs={
                "feed_id": feed.id,
                "url": urljoin(base_url, link) if link else "",
                "title": entry.get("title") or "",
                "summary": entry.get("summary") or "",
                "body": body_html,
                "guid": entry.get("id") or entry.get("guid") or "",
                "author": entry.get("author"),
                "published_at": published.isoformat() if published else None,
                "feed_language": feed.language,
            }
        )

    moved = _follow_permanent_redirect(feed, result)
    meta = parsed.get("feed") or {}
    feed.title = plain_text(meta.get("title"), 500) or feed.title
    site_url = str(meta.get("link") or "")
    if site_url.startswith(("https://", "http://")):
        feed.site_url = site_url[:MAX_URL_CHARS]
    feed.etag = result.etag or feed.etag
    feed.last_modified = result.last_modified or feed.last_modified
    feed.last_status = FeedStatus.OK
    feed.consecutive_errors = 0
    feed.disabled_until = None
    _save(
        feed,
        [
            *moved,
            "title",
            "site_url",
            "etag",
            "last_modified",
            "last_status",
            "last_fetched_at",
            "consecutive_errors",
            "disabled_until",
            "updated_at",
        ],
    )
    return {"status": FeedStatus.OK, "entries": min(len(entries), settings.MAX_ENTRIES_PER_FETCH)}
