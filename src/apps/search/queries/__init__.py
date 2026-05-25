"""Raw SQL loaded from sibling .sql files for FTS search and fuzzy fallback."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from django.db import connection

SUPPORTED_LANGS = ("russian", "english", "simple")
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
    aliases = {"ru": "russian", "en": "english"}
    return aliases.get(lang, "simple")


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
    }
    sql = SEARCH_DATE_SQL if sort == "date" else SEARCH_RANK_SQL
    with connection.cursor() as cur:
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
    if rows or len(query) > 24:
        return rows
    return run_trgm_fallback(query=query, limit=limit, offset=offset)


def run_trgm_fallback(*, query: str, limit: int, offset: int) -> list[dict[str, Any]]:
    with connection.cursor() as cur:
        cur.execute(TRGM_FALLBACK_SQL, {"query": query, "limit": limit, "offset": offset})
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
