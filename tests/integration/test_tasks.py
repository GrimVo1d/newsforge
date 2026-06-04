from __future__ import annotations

import socket
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.articles.models import Article
from apps.feeds import ratelimit, robots
from apps.feeds.fetcher import FetchResult
from apps.feeds.models import Feed, FeedStatus
from apps.subscriptions.models import Subscription
from apps.tags.models import ArticleTag, Tag, TagRule
from tasks.fetcher import fetch_feed
from tasks.scheduler import cleanup_old_articles, enqueue_due_feeds, refresh_robots_cache

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).parent.parent / "fixtures" / "feeds"


@pytest.fixture(autouse=True)
def clean_redis(feed):
    cache.clear()
    ratelimit.reset("example.internal")
    yield
    cache.clear()
    ratelimit.reset("example.internal")


@pytest.fixture
def allow_robots():
    with patch("tasks.fetcher.is_allowed", return_value=True):
        yield


def _fetch_returns(result: FetchResult):
    return patch("tasks.fetcher.fetch", return_value=result)


def _ok(body: bytes, etag: str | None = '"v1"') -> FetchResult:
    return FetchResult("ok", 200, body, etag, "Mon, 04 May 2026 12:00:00 GMT")


def test_fetch_feed_ingests_entries_and_updates_feed(feed, allow_robots):
    body = b"\xef\xbb\xbf" + (FIXTURES / "sample_en.xml").read_bytes()
    with _fetch_returns(_ok(body)):
        assert fetch_feed(feed.id) == {"status": FeedStatus.OK, "entries": 2}

    feed.refresh_from_db()
    assert (feed.title, feed.site_url, feed.etag) == (
        "Sample EN feed",
        "https://example.internal",
        '"v1"',
    )
    assert feed.last_status == FeedStatus.OK
    titles = set(Article.objects.values_list("title", flat=True))
    assert titles == {"Django release 5.1 ships new features", "What is new in DRF 3.16"}
    first = Article.objects.get(guid="post-1")
    assert first.published_at.isoformat() == "2026-05-04T12:00:00+00:00"

    with _fetch_returns(_ok(body)):
        fetch_feed(feed.id)
    assert Article.objects.count() == 2


def test_fetch_feed_caps_entries(feed, allow_robots, settings):
    settings.MAX_ENTRIES_PER_FETCH = 1
    with _fetch_returns(_ok((FIXTURES / "sample_en.xml").read_bytes())):
        assert fetch_feed(feed.id)["entries"] == 1
    assert Article.objects.count() == 1


def test_fetch_feed_failure_backs_off(feed, allow_robots):
    before = timezone.now()
    with _fetch_returns(FetchResult("http_error", 503, None, None, None)):
        assert fetch_feed(feed.id) == {"status": "http_error"}
    feed.refresh_from_db()
    assert feed.consecutive_errors == 1
    assert feed.next_fetch_at > before


def test_fetch_feed_parse_error(feed, allow_robots):
    with _fetch_returns(_ok(b"<html>not a feed")):
        assert fetch_feed(feed.id) == {"status": FeedStatus.PARSE_ERROR}


def test_fetch_feed_not_modified_resets_errors(feed, allow_robots):
    feed.consecutive_errors = 3
    feed.save()
    with _fetch_returns(FetchResult("not_modified", 304, None, None, None)):
        assert fetch_feed(feed.id) == {"status": FeedStatus.NOT_MODIFIED}
    feed.refresh_from_db()
    assert feed.consecutive_errors == 0


def test_fetch_feed_respects_robots_and_rate_limit(feed):
    with patch("tasks.fetcher.is_allowed", return_value=False):
        assert fetch_feed(feed.id) == {"status": FeedStatus.ROBOTS_BLOCKED}
    with patch("tasks.fetcher.is_allowed", return_value=True), _fetch_returns(_ok(b"")):
        assert ratelimit.try_acquire(feed.url)
        assert fetch_feed(feed.id) == {"status": "rate_limited"}


def test_fetch_feed_skips_deleted_feed(feed):
    feed.is_deleted = True
    feed.save()
    assert fetch_feed(feed.id) == {"status": "gone"}


def test_new_article_is_tagged_before_fanout(user, feed, allow_robots, monkeypatch):
    tag = Tag.objects.create(name="Django", slug="django")
    TagRule.objects.create(owner=user, name="dj", keywords=["django"], tag=tag)
    sub = Subscription.objects.create(
        owner=user,
        name="dj",
        q="django",
        delivery="email",
        email_to="me@example.internal",
        tag_ids=[tag.id],
    )
    from tasks.notifications import deliver

    queued: list[tuple[int, int]] = []
    monkeypatch.setattr(deliver, "apply_async", lambda args: queued.append(args))
    with _fetch_returns(_ok((FIXTURES / "sample_en.xml").read_bytes())):
        fetch_feed(feed.id)

    tagged = Article.objects.get(guid="post-1")
    assert ArticleTag.objects.filter(article=tagged, tag=tag).exists()
    assert queued == [(sub.id, tagged.id)]


def test_enqueue_due_feeds(feed):
    Feed.objects.create(
        url="https://later.example.internal/rss", next_fetch_at=timezone.now() + timedelta(hours=1)
    )
    Feed.objects.create(
        url="https://off.example.internal/rss",
        disabled_until=timezone.now() + timedelta(hours=1),
        next_fetch_at=timezone.now() - timedelta(minutes=1),
    )
    feed.next_fetch_at = timezone.now() - timedelta(minutes=1)
    feed.save()

    with patch("tasks.fetcher.fetch_feed.apply_async") as apply_async:
        assert enqueue_due_feeds() == {"enqueued": 1}
    apply_async.assert_called_once_with(args=(feed.id,))
    feed.refresh_from_db()
    assert feed.next_fetch_at > timezone.now() + timedelta(seconds=feed.interval_seconds - 60)


def test_cleanup_old_articles(make_article):
    old, fresh = make_article("Old news"), make_article("Fresh news")
    Article.objects.filter(pk=old.pk).update(published_at=timezone.now() - timedelta(days=400))
    Article.objects.filter(pk=fresh.pk).update(published_at=timezone.now())
    assert cleanup_old_articles() == {"soft_deleted": 1}
    assert Article.objects.get(pk=old.pk).is_deleted


def test_refresh_robots_cache(feed):
    cache.set("robots:example.internal", "cached")
    assert refresh_robots_cache() == {"invalidated": 1}
    assert cache.get("robots:example.internal") is None


# --- robots.txt ----------------------------------------------------------------


@pytest.fixture
def public_dns():
    def fake(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    with patch("apps.core.safe_http.socket.getaddrinfo", side_effect=fake):
        yield


def _robots_response(response: httpx.Response | Exception):
    def fake_request(method, url, **kwargs):
        if isinstance(response, Exception):
            raise response
        return robots.safe_http.Response(
            response.status_code, response.headers, response.content, url
        )

    return patch.object(robots.safe_http, "request", side_effect=fake_request)


ROBOTS = b"User-agent: *\nDisallow: /private/\n"


def test_robots_rules_are_applied_and_cached(public_dns):
    with _robots_response(httpx.Response(200, content=ROBOTS)) as req:
        assert robots.is_allowed("https://example.internal/feed.xml")
        assert not robots.is_allowed("https://example.internal/private/feed.xml")
    assert req.call_count == 1
    assert req.call_args.kwargs["max_bytes"] == robots.MAX_ROBOTS_BYTES


@pytest.mark.parametrize(
    "response, allowed",
    [
        (httpx.Response(404), True),
        (httpx.ConnectError("down"), True),
        (robots.safe_http.UnsafeURLError("private"), False),
    ],
)
def test_robots_failures(public_dns, response, allowed):
    with _robots_response(response):
        assert robots.is_allowed("https://example.internal/private/feed.xml") is allowed
