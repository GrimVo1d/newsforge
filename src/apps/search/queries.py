"""Raw SQL for FTS search and fuzzy fallback."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db import connection

SUPPORTED_LANGS = ("russian", "english", "simple")


def coerce_lang(lang: str | None) -> str:
    """Whitelist regconfig names — never interpolate user input into SQL."""
    if not lang:
        return "simple"
    lang = lang.lower()
    if lang in SUPPORTED_LANGS:
        return lang
    aliases = {"ru": "russian", "en": "english"}
    return aliases.get(lang, "simple")


SEARCH_RANK_SQL = """
WITH q AS (
  SELECT websearch_to_tsquery(%(cfg)s::regconfig, unaccent(%(query)s)) AS tsq
)
SELECT
  a.id, a.title, a.summary, a.url, a.feed_id, a.published_at, a.language,
  ts_rank_cd(a.tsv, q.tsq, 32) AS rank,
  ts_headline(
    %(cfg)s::regconfig,
    coalesce(a.summary, ''),
    q.tsq,
    'MaxFragments=2, MinWords=5, MaxWords=20, StartSel=<b>, StopSel=</b>'
  ) AS highlight
FROM articles_article a, q
WHERE NOT a.is_deleted
  AND a.tsv @@ q.tsq
  AND (%(from)s::timestamptz IS NULL OR a.published_at >= %(from)s)
  AND (%(to)s::timestamptz   IS NULL OR a.published_at <  %(to)s)
  AND (cardinality(%(feeds)s::bigint[]) = 0 OR a.feed_id = ANY(%(feeds)s))
ORDER BY rank DESC, a.published_at DESC NULLS LAST
LIMIT %(limit)s OFFSET %(offset)s;
"""

SEARCH_DATE_SQL = """
WITH q AS (
  SELECT websearch_to_tsquery(%(cfg)s::regconfig, unaccent(%(query)s)) AS tsq
)
SELECT
  a.id, a.title, a.summary, a.url, a.feed_id, a.published_at, a.language,
  0::float AS rank, '' AS highlight
FROM articles_article a, q
WHERE NOT a.is_deleted
  AND a.tsv @@ q.tsq
  AND (%(from)s::timestamptz IS NULL OR a.published_at >= %(from)s)
  AND (%(to)s::timestamptz   IS NULL OR a.published_at <  %(to)s)
  AND (cardinality(%(feeds)s::bigint[]) = 0 OR a.feed_id = ANY(%(feeds)s))
ORDER BY a.published_at DESC NULLS LAST
LIMIT %(limit)s OFFSET %(offset)s;
"""


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
        return [dict(zip(cols, row)) for row in cur.fetchall()]
