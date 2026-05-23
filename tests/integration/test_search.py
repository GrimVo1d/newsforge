from __future__ import annotations

import pytest

from apps.articles.normalizer import normalize_entry
from apps.articles.services import upsert_article
from apps.search.queries import run_search


@pytest.fixture(autouse=True)
def _skip_on_non_pg(db):
    from django.db import connection

    if connection.vendor != "postgresql":
        pytest.skip("postgres-only test")


def test_websearch_finds_inserted_article(feed):
    entry = normalize_entry(
        url="https://example.com/p/1",
        title="Django release 5.1 ships new features",
        summary="Django 5.1 introduces DRF improvements and async views",
        body="",
        guid="post-1",
    )
    upsert_article(feed.id, entry)
    results = run_search(query="django release", lang="english", sort="rank")
    assert any("Django" in r["title"] for r in results)
    top = results[0]
    assert top["rank"] >= 0
    assert "<b>" in top["highlight"] or top["highlight"] == ""


def test_search_filter_by_feed(feed):
    entry = normalize_entry(
        url="https://example.com/p/2",
        title="DRF 3.16 typed views and openapi",
        summary="What is new in DRF 3.16",
        body="",
        guid="post-2",
    )
    upsert_article(feed.id, entry)
    found = run_search(query="DRF", feeds=[feed.id], lang="english")
    assert all(r["feed_id"] == feed.id for r in found)
