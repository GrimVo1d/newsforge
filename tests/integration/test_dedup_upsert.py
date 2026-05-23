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
        url="https://example.com/p/1", title="hello", summary="s", body="b", guid="g-1"
    )
    r1 = upsert_article(feed.id, entry)
    r2 = upsert_article(feed.id, entry)
    assert r1.inserted is True
    assert r2.inserted is False
    assert r1.article_id == r2.article_id


def test_upsert_by_content_hash_when_no_guid(feed):
    entry = normalize_entry(url="https://example.com/p/2", title="t", summary="", body="b")
    r1 = upsert_article(feed.id, entry)
    r2 = upsert_article(feed.id, entry)
    assert r1.inserted is True
    assert r2.inserted is False
