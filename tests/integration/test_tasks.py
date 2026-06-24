from __future__ import annotations

import socket
import time
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
    feed.consecutive_errors = 6
    feed.disabled_until = timezone.now() - timedelta(minutes=1)  # a pause that just ended
    feed.save()
    with _fetch_returns(FetchResult("not_modified", 304, None, None, None)):
        assert fetch_feed(feed.id) == {"status": FeedStatus.NOT_MODIFIED}
    feed.refresh_from_db()
    assert (feed.consecutive_errors, feed.disabled_until) == (0, None)


def test_rate_limited_feed_is_retried_soon(feed, allow_robots, settings):
    assert ratelimit.try_acquire(feed.url)
    before = timezone.now()
    with _fetch_returns(_ok(b"")) as fetch:
        assert fetch_feed(feed.id) == {"status": "rate_limited"}
    fetch.assert_not_called()
    feed.refresh_from_db()
    interval = timedelta(seconds=settings.PER_DOMAIN_MIN_INTERVAL)
    assert before + interval <= feed.next_fetch_at <= timezone.now() + 2 * interval


@pytest.mark.parametrize("status", ["ok", "not_modified"])
def test_permanent_redirect_moves_the_feed(feed, allow_robots, status):
    new_url = "https://new.example.internal/feed.xml"
    body = (FIXTURES / "sample_en.xml").read_bytes() if status == "ok" else None
    result = FetchResult(status, 200, body, None, None, permanent_url=new_url)
    with _fetch_returns(result):
        fetch_feed(feed.id)
    feed.refresh_from_db()
    assert feed.url == new_url


def test_permanent_redirect_to_another_feed_keeps_the_url(feed, allow_robots):
    other = Feed.objects.create(url="https://new.example.internal/feed.xml", is_deleted=True)
    body = (FIXTURES / "sample_en.xml").read_bytes()
    with _fetch_returns(FetchResult("ok", 200, body, None, None, permanent_url=other.url)):
        assert fetch_feed(feed.id)["status"] == FeedStatus.OK
    feed.refresh_from_db()
    assert feed.url == "https://example.internal/feed.xml"


def test_permanent_redirect_target_is_stored_canonical(feed, allow_robots):
    result = FetchResult(
        "not_modified", 304, None, None, None, permanent_url="https://NEW.example.internal:443/f#x"
    )
    with _fetch_returns(result):
        fetch_feed(feed.id)
    feed.refresh_from_db()
    assert feed.url == "https://new.example.internal/f"


def test_permanent_redirect_to_an_overlong_url_is_ignored(feed, allow_robots):
    long_url = "https://new.example.internal/" + "a" * 2048
    result = FetchResult("not_modified", 304, None, None, None, permanent_url=long_url)
    with _fetch_returns(result):
        assert fetch_feed(feed.id) == {"status": FeedStatus.NOT_MODIFIED}
    feed.refresh_from_db()
    assert feed.url == "https://example.internal/feed.xml"


def test_concurrent_move_to_the_same_url_keeps_the_feed_where_it_was(feed):
    from tasks.fetcher import _save

    other = Feed.objects.create(url="https://new.example.internal/feed.xml")
    feed.url, feed.last_status = other.url, FeedStatus.OK
    _save(feed, ["url", "last_status", "updated_at"])
    feed.refresh_from_db()
    assert (feed.url, feed.last_status) == ("https://example.internal/feed.xml", FeedStatus.OK)


def test_entry_dates_are_robust():
    import feedparser

    from tasks.fetcher import _entry_published

    rss = (FIXTURES / "sample_en.xml").read_text()
    leap = feedparser.parse(rss).entries[0]
    leap["published_parsed"] = (2025, 12, 31, 23, 59, 60, 2, 365, 0)
    assert _entry_published(leap).second == 59
    leap["published_parsed"] = (2025, 13, 45, 0, 0, 0, 0, 0, 0)
    assert _entry_published(leap) is None


def test_future_dates_are_clamped_to_now(feed):
    from tasks.articles import process_article

    res = process_article(
        feed_id=feed.id,
        url="https://example.internal/f",
        title="From the future",
        guid="f1",
        published_at="2099-01-01T00:00:00+00:00",
    )
    assert Article.objects.get(pk=res["article_id"]).published_at <= timezone.now()


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
    apply_async.assert_called_once_with(args=(feed.id,), expires=feed.interval_seconds)
    feed.refresh_from_db()
    assert feed.next_fetch_at > timezone.now() + timedelta(seconds=feed.interval_seconds - 60)


def test_cleanup_old_articles(make_article, monkeypatch):
    monkeypatch.setattr("tasks.scheduler.CLEANUP_BATCH", 1)  # several batches
    old, undated, fresh = (make_article(t) for t in ("Old news", "Undated", "Fresh news"))
    long_ago = timezone.now() - timedelta(days=400)
    Article.objects.filter(pk=old.pk).update(published_at=long_ago)
    Article.objects.filter(pk=undated.pk).update(published_at=None, created_at=long_ago)
    Article.objects.filter(pk=fresh.pk).update(published_at=timezone.now())
    assert cleanup_old_articles() == {"soft_deleted": 2}
    assert set(Article.objects.filter(is_deleted=True).values_list("pk", flat=True)) == {
        old.pk,
        undated.pk,
    }


def test_due_feeds_have_no_unused_partial_index():
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = 'feeds_due_partial_idx'")
        assert cur.fetchone() is None


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
    "response, allowed, ttl",
    [
        (httpx.Response(404), True, robots.CACHE_TTL_SECONDS),
        (httpx.Response(503), False, robots.RETRY_TTL_SECONDS),
        (httpx.ConnectError("down"), False, robots.RETRY_TTL_SECONDS),
        # allowed here, so that the feed fetch itself reports ssrf_blocked
        (robots.safe_http.UnsafeURLError("private"), True, robots.RETRY_TTL_SECONDS),
    ],
)
def test_robots_failures(public_dns, response, allowed, ttl):
    with _robots_response(response):
        assert robots.is_allowed("https://example.internal/private/feed.xml") is allowed
    remaining = ratelimit.redis_client().ttl(cache.make_key("robots:example.internal"))
    assert ttl - 60 < remaining <= ttl


def test_robots_uses_the_configured_product_token(public_dns, settings):
    settings.USER_AGENT = "acmebot/2.0 (+https://acme.example.internal/bot)"
    body = b"User-agent: *\nAllow: /\n\nUser-agent: AcmeBot\nDisallow: /\n"
    with _robots_response(httpx.Response(200, content=body)):
        assert not robots.is_allowed("https://example.internal/feed.xml")
    assert robots.product_token() == "acmebot"


@pytest.mark.parametrize(
    "rules, path, allowed",
    [
        ("Disallow: /\nAllow: /feed.xml", "/feed.xml", True),  # longest match wins
        ("Allow: /feed\nDisallow: /feed.xml", "/feed.xml", False),
        ("Allow: /a\nDisallow: /a", "/a", True),  # tie: allow wins
        ("Disallow: /*.xml$", "/feed.xml", False),
        ("Disallow: /*.xml$", "/feed.xml?x=1", True),
        ("Disallow: /private", "/private-feed", False),  # prefix match
        ("Disallow:", "/feed.xml", True),  # empty rule matches nothing
        ("Disallow: /%7Euser/", "/~user/feed", False),  # percent-encoding is normalized
        ("Disallow: /", "/robots.txt", True),
        ("Disallow: /a*b*c", "/a-x-b-y-c-z", False),  # wildcards in order
        ("Disallow: /a*b*c", "/a-x-c-y-b", True),  # ... and only in that order
        ("Disallow: /a*c*b$", "/a-x-c-y-b", False),
        ("Disallow: /a*c*b$", "/a-x-c-y-b-z", True),
        ("Disallow: /$", "/", False),
        ("Disallow: /$", "/feed.xml", True),
        ("Disallow: *", "/feed.xml", False),
    ],
)
def test_robots_rule_matching(rules, path, allowed):
    body = f"User-agent: *\n{rules}\n"
    assert robots.can_fetch(body, f"https://example.internal{path}", "newsforge") is allowed


def test_robots_groups_for_one_agent_are_merged():
    body = (
        "User-agent: other\nUser-agent: newsforge\nDisallow: /a\n\n"
        "User-agent: *\nDisallow: /\n\n"
        "User-agent: NewsForge\nDisallow: /b\n"
    )
    assert not robots.can_fetch(body, "https://example.internal/a", "newsforge")
    assert not robots.can_fetch(body, "https://example.internal/b", "newsforge")
    assert robots.can_fetch(body, "https://example.internal/c", "newsforge")
    assert not robots.can_fetch(body, "https://example.internal/c", "otherbot")


def test_robots_explicit_allow_group_is_not_ignored():
    # The group for our token exists although its only rule is empty: "*" does not apply.
    body = "User-agent: newsforge/0.1\nDisallow:\n\nUser-agent: *\nDisallow: /\n"
    assert robots.can_fetch(body, "https://example.internal/feed.xml", "newsforge")
    assert not robots.can_fetch(body, "https://example.internal/feed.xml", "otherbot")


def test_robots_matching_is_linear_for_hostile_patterns():
    body = "User-agent: *\n" + "Disallow: /" + "*a" * 40 + "*b\n"
    started = time.monotonic()
    assert robots.can_fetch(body, "https://example.internal/" + "a" * 2000, "newsforge")
    assert time.monotonic() - started < 1


def test_robots_rules_are_capped():
    body = "User-agent: *\n" + "Allow: /x\n" * robots.MAX_RULES + "Disallow: /\n"
    assert robots.can_fetch(body, "https://example.internal/feed.xml", "newsforge")


@pytest.mark.parametrize("agent", ["*", "newsforge"])
def test_robots_rules_are_stored_once_per_group(agent):
    # Thousands of User-agent lines in front of the rules must not multiply them.
    body = f"User-agent: {agent}\n" * 30_000 + "Disallow: /private\n" * robots.MAX_RULES
    robots._rules_for.cache_clear()
    started = time.monotonic()
    rules = robots._rules_for(body, "newsforge")
    assert not robots.can_fetch(body, "https://example.internal/private/x", "newsforge")
    assert len(rules) == robots.MAX_RULES
    assert time.monotonic() - started < 2
    robots._rules_for.cache_clear()


def test_robots_rules_of_other_agents_do_not_count():
    other = "User-agent: otherbot\n" + "Disallow: /x\n" * robots.MAX_RULES
    body = other + "\nUser-agent: *\nDisallow: /private\n"
    assert not robots.can_fetch(body, "https://example.internal/private/x", "newsforge")


def test_relative_links_and_http_charset(feed, allow_robots):
    title = "Новости дня"
    body = (
        f'<?xml version="1.0"?><rss version="2.0"><channel><title>{title}</title>'
        f"<item><guid>r1</guid><link>/posts/1</link><title>{title}</title></item>"
        "<item><guid>r2</guid><link>javascript:alert(1)</link><title>x</title></item>"
        "</channel></rss>"
    ).encode("cp1251")
    result = FetchResult(
        "ok",
        200,
        body,
        None,
        None,
        url="https://cdn.example.internal/feeds/main.xml",
        content_type="application/rss+xml; charset=windows-1251",
    )
    with _fetch_returns(result):
        assert fetch_feed(feed.id)["status"] == FeedStatus.OK
    article = Article.objects.get(guid="r1")
    assert (article.title, article.url) == (title, "https://cdn.example.internal/posts/1")
    feed.refresh_from_db()
    assert feed.title == title


def test_tag_rules_match_visible_text(user, make_article):
    from apps.articles.normalizer import normalize_entry
    from apps.articles.services import upsert_article
    from apps.tags.engine import apply_rules_to_article

    furniture = Tag.objects.create(name="Furniture", slug="furniture")
    telco = Tag.objects.create(name="ATT", slug="att")
    TagRule.objects.create(owner=user, name="t", keywords=["table"], tag=furniture)
    TagRule.objects.create(owner=user, name="a", keywords=["at&t"], tag=telco)
    entry = normalize_entry(
        url="https://example.internal/m",
        title="Quarterly results",
        guid="m1",
        summary="<p>AT&amp;T posted results</p>",
        body="<table><tr><td>1</td></tr></table>",
    )
    feed_id = make_article("seed").feed_id
    assigned = apply_rules_to_article(upsert_article(feed_id, entry).article_id)
    assert assigned == [telco.id]
