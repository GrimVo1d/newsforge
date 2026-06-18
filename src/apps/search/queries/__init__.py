"""Raw SQL loaded from sibling .sql files for FTS search and fuzzy fallback."""

from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from django.db import connection

SUPPORTED_LANGS = ("russian", "english", "simple")
LANG_ALIASES = {"ru": "russian", "en": "english"}
# Longer queries are phrases, not typos; trigram similarity on them is noise.
TRGM_MAX_QUERY_CHARS = 24
_HERE = Path(__file__).parent

# ts_headline marks matches with two private-use characters instead of <b>/</b>: the snippet is
# escaped first and only then given its tags, so nothing in the text can become markup.
MARK_START, MARK_STOP = "\ue000", "\ue001"
HEADLINE_OPTIONS = (
    f'MaxFragments=2, MinWords=5, MaxWords=20, StartSel="{MARK_START}", StopSel="{MARK_STOP}"'
)
_MARKS = re.compile(f"([{MARK_START}{MARK_STOP}])")
_TAGS = {MARK_START: "<b>", MARK_STOP: "</b>"}


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
        "marks": MARK_START + MARK_STOP,
        "headline_options": HEADLINE_OPTIONS,
    }
    sql = SEARCH_DATE_SQL if sort == "date" else SEARCH_RANK_SQL
    rows = _fetch(sql, params)
    for row in rows:
        row["highlight"] = render_highlight(row["highlight"])
    if rows or len(query) > TRGM_MAX_QUERY_CHARS:
        return rows
    if offset and _fetch(sql, {**params, "limit": 1, "offset": 0}):
        return rows  # paged past the last full-text hit; not a reason to go fuzzy
    # Nothing matched as words: try fuzzy title similarity (typos, partial words).
    return _fetch(TRGM_FALLBACK_SQL, params)


def render_highlight(raw: str) -> str:
    """HTML-escape a ts_headline snippet and turn its marks into <b>/</b>.

    The summary is stored as sanitized HTML, so entities are decoded before escaping: the
    result is plain text whose only markup is the marks.
    """
    return "".join(
        _TAGS.get(part) or html.escape(html.unescape(part)) for part in _MARKS.split(raw)
    )


def _fetch(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with connection.cursor() as cur:
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
