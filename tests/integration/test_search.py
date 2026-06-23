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
        url="https://example.internal/p/1",
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
        url="https://example.internal/p/2",
        title="DRF 3.16 typed views and openapi",
        summary="What is new in DRF 3.16",
        body="",
        guid="post-2",
    )
    upsert_article(feed.id, entry)
    found = run_search(query="DRF", feeds=[feed.id], lang="english")
    assert all(r["feed_id"] == feed.id for r in found)


@pytest.mark.parametrize("query", ["Djangoo releese", "kubernets"])
def test_fuzzy_fallback_uses_the_trigram_index(query):
    from django.db import connection

    from apps.search.queries import TRGM_FALLBACK_SQL

    params = {"query": query, "from": None, "to": None, "feeds": [], "limit": 20, "offset": 0}
    with connection.cursor() as cur:
        # The test table is tiny: forbid the scans the planner would prefer for that.
        cur.execute("SET LOCAL enable_seqscan = off; SET LOCAL enable_indexscan = off;")
        cur.execute("EXPLAIN " + TRGM_FALLBACK_SQL, {**params, "by_date": False})
        plan = "\n".join(row[0] for row in cur.fetchall())
    assert "articles_title_trgm_idx" in plan, plan


@pytest.mark.parametrize("cfg", [None, "english"])
def test_full_text_uses_the_tsv_index(cfg):
    from django.db import connection

    from apps.search.queries import HEADLINE_OPTIONS, MARK_START, MARK_STOP, SEARCH_RANK_SQL

    params = {
        "cfg": cfg,
        "query": '"security issues" -celery',
        "from": None,
        "to": None,
        "feeds": [],
        "limit": 20,
        "offset": 0,
        "by_date": False,
        "marks": MARK_START + MARK_STOP,
        "headline_options": HEADLINE_OPTIONS,
    }
    with connection.cursor() as cur:
        cur.execute("SET LOCAL enable_seqscan = off; SET LOCAL enable_indexscan = off;")
        cur.execute("EXPLAIN " + SEARCH_RANK_SQL, params)
        plan = "\n".join(row[0] for row in cur.fetchall())
    assert "articles_tsv_idx" in plan, plan
