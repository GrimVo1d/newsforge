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


def test_edited_entry_is_updated_in_place(feed):
    from apps.articles.models import Article

    first = upsert_article(feed.id, _entry(guid="g-1", title="Typo titel"))
    fixed = upsert_article(feed.id, _entry(guid="g-1", title="Fixed title"))
    assert (fixed.inserted, fixed.updated, fixed.article_id) == (False, True, first.article_id)
    article = Article.objects.get(pk=first.article_id)
    assert article.title == "Fixed title"
    assert article.content_hash == _entry(title="Fixed title").content_hash


def test_edit_matching_another_row_only_touches(feed):
    from apps.articles.models import Article

    other = upsert_article(feed.id, _entry(title="Taken"))
    mine = upsert_article(feed.id, _entry(guid="g-1"))
    again = upsert_article(feed.id, _entry(guid="g-1", title="Taken"))
    assert (again.updated, again.article_id) == (False, mine.article_id)
    assert Article.objects.get(pk=mine.article_id).title == "Same story"
    assert Article.objects.get(pk=other.article_id).title == "Taken"


def test_distinct_entries_with_a_shared_prefix_are_kept(feed):
    boiler = "x" * 600
    a = normalize_entry(
        url="https://example.internal/weekly",
        title="Weekly",
        summary="",
        body=f"<p>{boiler} week 1</p>",
        guid="w1",
    )
    b = normalize_entry(
        url="https://example.internal/weekly",
        title="Weekly",
        summary="",
        body=f"<p>{boiler} week 2</p>",
        guid="w2",
    )
    r1, r2 = upsert_article(feed.id, a), upsert_article(feed.id, b)
    assert r1.inserted and r2.inserted


def test_huge_and_odd_entries_are_stored(feed):
    import random
    import string

    rnd = random.Random(1)
    words = " ".join("".join(rnd.choices(string.ascii_lowercase, k=10)) for _ in range(150_000))
    big = normalize_entry(
        url="https://example.internal/big",
        title="big",
        summary="",
        body=f"<p>{words}</p>",
        guid="big",
    )
    assert upsert_article(feed.id, big).inserted
    long_guid = "".join(rnd.choices(string.ascii_letters, k=4000))
    odd = normalize_entry(
        url="https://example.internal/n\x00",
        title="t\x00",
        summary="s\x00",
        body="b\x00",
        guid=long_guid,
        author="a\x00",
    )
    assert odd.guid.startswith("sha256:")
    assert upsert_article(feed.id, odd).inserted
    nul = normalize_entry(
        url="https://example.internal/m", title="t", summary="", body="", guid="a\x00b"
    )
    assert upsert_article(feed.id, nul).inserted


def test_trigger_does_not_depend_on_search_path(feed):
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SET LOCAL search_path = ''")
        cur.execute(
            "INSERT INTO public.articles_article (feed_id, guid, canonical_url, url, title,"
            " summary, body, language, content_hash, fetched_at, last_seen_at, is_deleted,"
            " created_at) VALUES (%s, 'sp', 'u', 'u', 'Café', '', '', 'simple', 'h', now(),"
            " now(), false, now()) RETURNING tsv::text",
            [feed.id],
        )
        assert cur.fetchone()[0] == "'cafe':1A"
        cur.execute("RESET search_path")


def test_redelivered_task_still_tags_and_fans_out(feed, user):
    from unittest.mock import patch

    from apps.articles.models import Article
    from apps.tags.models import ArticleTag, Tag, TagRule
    from tasks.articles import process_article

    tag = Tag.objects.create(name="Django", slug="django")
    TagRule.objects.create(owner=user, name="dj", keywords=["django"], tag=tag)
    kwargs = {
        "feed_id": feed.id,
        "url": "https://example.internal/p/1",
        "title": "Django ships",
        "guid": "g-1",
    }
    broker_down = patch("apps.articles.receivers.chain", side_effect=ConnectionError("down"))
    with broker_down, pytest.raises(ConnectionError):
        process_article(**kwargs)
    assert Article.objects.get(guid="g-1").processed_at is None
    again = process_article(**kwargs)
    assert again["inserted"] is False
    article = Article.objects.get(guid="g-1")
    assert article.processed_at is not None
    assert ArticleTag.objects.filter(article=article, tag=tag).exists()


def test_article_is_processed_once(feed):
    from unittest.mock import patch

    from tasks.articles import process_article

    kwargs = {"feed_id": feed.id, "url": "https://example.internal/p/1", "title": "t"}
    with patch("apps.articles.receivers.chain") as chain:
        process_article(**kwargs)
        process_article(**kwargs)
    assert chain.call_count == 1


def test_feed_language_is_the_fallback(feed):
    from apps.articles.models import Article
    from tasks.articles import process_article

    res = process_article(
        feed_id=feed.id,
        url="https://example.internal/s",
        title="Новости",
        guid="s1",
        feed_language="russian",
    )
    assert Article.objects.get(pk=res["article_id"]).language == "russian"


def test_rehash_migration_matches_content_hash(feed):
    import importlib

    from django.db import connection

    from apps.articles.models import Article

    migration = importlib.import_module(
        "apps.articles.migrations.0006_trigger_search_path_and_full_hash"
    )
    entries = [
        normalize_entry(
            url="https://example.internal/1",
            title="Body",
            summary="s",
            body="<p>Ünïcode body</p>\n" * 50,
            guid="1",
        ),
        normalize_entry(
            url="https://example.internal/2",
            title="Summary only",
            summary="  <b>text</b>  ",
            body="",
            guid="2",
        ),
    ]
    for entry in entries:
        upsert_article(feed.id, entry)
    expected = dict(Article.objects.values_list("guid", "content_hash"))
    with connection.cursor() as cur:
        cur.execute("UPDATE articles_article SET content_hash = 'stale-' || id")
        cur.execute(migration.REHASH_SQL)
    assert dict(Article.objects.values_list("guid", "content_hash")) == expected
