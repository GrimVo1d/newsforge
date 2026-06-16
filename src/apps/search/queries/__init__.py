"""Raw SQL loaded from sibling .sql files for FTS search and fuzzy fallback."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from django.db import connection

SUPPORTED_LANGS = ("russian", "english", "simple")
LANG_ALIASES = {"ru": "russian", "en": "english"}
# Longer queries are phrases, not typos; trigram similarity on them is noise.
TRGM_MAX_QUERY_CHARS = 24
_HERE = Path(__file__).parent


def _load(name: str) -> str:
    return (_HERE / name).read_text(encoding="utf-8")


SEARCH_RANK_SQL = _load("search_rank.sql")
SEARCH_DATE_SQL = _load("search_date.sql")
TRGM_FALLBACK_SQL = _load("trgm_fallback.sql")


def coerce_lang(lang: str | None) -> str:
    """Whitelist regconfig names — never interpolate user input into SQL."""
    if not lang:
        return "simple"
    lang = lang.lower()
    if lang in SUPPORTED_LANGS:
        return lang
    return LANG_ALIASES.get(lang, "simple")


def run_search(
    *,
    query: str,
    lang: str | None = None,
    sort: str = "rank",
    feeds: list[int] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    cfg = coerce_lang(lang)
    params = {
        "cfg": cfg,
        "query": query,
        "feeds": feeds or [],
        "from": date_from,
        "to": date_to,
        "limit": limit,
        "offset": offset,
        "by_date": sort == "date",
    }
    sql = SEARCH_DATE_SQL if sort == "date" else SEARCH_RANK_SQL
    rows = _fetch(sql, params)
    if rows or len(query) > TRGM_MAX_QUERY_CHARS:
        return rows
    if offset and _fetch(sql, {**params, "limit": 1, "offset": 0}):
        return rows  # paged past the last full-text hit; not a reason to go fuzzy
    # Nothing matched as words: try fuzzy title similarity (typos, partial words).
    return _fetch(TRGM_FALLBACK_SQL, params)


def _fetch(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with connection.cursor() as cur:
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
