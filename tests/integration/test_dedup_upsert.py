"""End-to-end dedup behaviour. Requires real PostgreSQL.

These tests are skipped on SQLite. The conftest provides a `feed` fixture; pytest-django
applies migrations against the configured `DATABASE_URL`.
"""

from __future__ import annotations

import pytest

from apps.articles.normalizer import normalize_entry
from apps.articles.services import upsert_article


@pytest.fixture(autouse=True)
def _skip_on_non_pg(db):
    from django.db import connection

    if connection.vendor != "postgresql":
        pytest.skip("postgres-only test")


def test_upsert_by_guid_does_not_create_duplicate(feed):
    entry = normalize_entry(
        url="https://example.internal/p/1", title="hello", summary="s", body="b", guid="g-1"
    )
    r1 = upsert_article(feed.id, entry)
    r2 = upsert_article(feed.id, entry)
    assert r1.inserted is True
    assert r2.inserted is False
    assert r1.article_id == r2.article_id


def test_upsert_by_content_hash_when_no_guid(feed):
    entry = normalize_entry(url="https://example.internal/p/2", title="t", summary="", body="b")
    r1 = upsert_article(feed.id, entry)
    r2 = upsert_article(feed.id, entry)
    assert r1.inserted is True
    assert r2.inserted is False


@pytest.fixture
def other_feed(db):
    from apps.feeds.models import Feed

    return Feed.objects.create(url="https://mirror.example.internal/feed.xml")


def _entry(guid: str = "", title: str = "Same story"):
    return normalize_entry(
        url="https://example.internal/p/same", title=title, summary="", body="body", guid=guid
    )


def test_same_story_in_two_feeds_is_stored_per_feed(feed, other_feed):
    a = upsert_article(feed.id, _entry(guid="g-1"))
    b = upsert_article(other_feed.id, _entry(guid="g-1"))
    c = upsert_article(other_feed.id, _entry())
    assert a.inserted and b.inserted
    assert a.article_id != b.article_id
    assert (c.inserted, c.article_id) == (False, b.article_id)


def test_new_guid_with_same_content_is_a_duplicate(feed):
    first = upsert_article(feed.id, _entry(guid="g-1"))
    again = upsert_article(feed.id, _entry(guid="g-2"))
    assert (again.inserted, again.article_id) == (False, first.article_id)


def test_guid_match_wins_over_hash_match(feed):
    by_hash = upsert_article(feed.id, _entry(title="Edited"))
    by_guid = upsert_article(feed.id, _entry(guid="g-1"))
    edited = upsert_article(feed.id, _entry(guid="g-1", title="Edited"))
    assert by_hash.article_id != by_guid.article_id
    assert (edited.inserted, edited.article_id) == (False, by_guid.article_id)


def test_process_article_skips_non_http_links(feed):
    from apps.articles.models import Article
    from tasks.articles import process_article

    result = process_article(feed_id=feed.id, url="javascript:alert(1)", title="x")
    assert "skipped" in result
    assert not Article.objects.exists()
