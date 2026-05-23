"""Cross-language ranking correctness: Russian and English regconfigs apply the right stemming."""

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


def test_russian_stemming_matches_inflected_form(feed):
    feed.language = "russian"
    feed.save(update_fields=["language"])

    # Russian word with inflection — "обновлении" should match query "обновление"
    entry = normalize_entry(
        url="https://example.ru/p/1",
        title="DRF 3.16 в обновлении",
        summary="Что нового в обновлении DRF",
        body="",
        guid="post-ru-1",
    )
    # Force language since auto-detect on short text returns simple.
    entry.language = "russian"
    upsert_article(feed.id, entry)

    results = run_search(query="обновление", lang="russian")
    titles = [r["title"] for r in results]
    assert any("обновлении" in t for t in titles)


def test_english_stemming_matches_plural(feed):
    feed.language = "english"
    feed.save(update_fields=["language"])

    entry = normalize_entry(
        url="https://example.com/p/2",
        title="Releases of Django framework",
        summary="Multiple framework releases this quarter",
        body="",
        guid="post-en-2",
    )
    entry.language = "english"
    upsert_article(feed.id, entry)

    results = run_search(query="release", lang="english")
    assert any("Releases" in r["title"] for r in results)
