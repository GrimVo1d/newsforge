"""Article upsert with deduplication inside a feed, by guid or by content_hash.

Both keys are unique per feed (``articles_feed_guid_uniq``, ``articles_feed_hash_uniq``), so
the same story in two feeds is stored twice, once per feed. An insert that hits either key
is a duplicate: the existing row only gets its ``last_seen_at`` bumped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import connection

from apps.articles.normalizer import NormalizedEntry


@dataclass(slots=True)
class UpsertResult:
    article_id: int
    inserted: bool


_INSERT = """
INSERT INTO articles_article
  (feed_id, guid, canonical_url, url, title, summary, body, author,
   language, content_hash, published_at, fetched_at, last_seen_at, is_deleted, created_at)
VALUES
  (%(feed_id)s, %(guid)s, %(canonical_url)s, %(url)s, %(title)s, %(summary)s, %(body)s, %(author)s,
   %(language)s, %(content_hash)s, %(published_at)s, now(), now(), false, now())
ON CONFLICT DO NOTHING
RETURNING id;
"""

# Prefer the guid match: an entry whose content changed keeps its row.
_TOUCH_EXISTING = """
UPDATE articles_article SET last_seen_at = now()
WHERE id = (
  SELECT id FROM articles_article
  WHERE feed_id = %(feed_id)s
    AND ((%(guid)s <> '' AND guid = %(guid)s) OR content_hash = %(content_hash)s)
  ORDER BY (%(guid)s <> '' AND guid = %(guid)s) DESC
  LIMIT 1
)
RETURNING id;
"""


def upsert_article(feed_id: int, entry: NormalizedEntry) -> UpsertResult:
    params: dict[str, Any] = {
        "feed_id": feed_id,
        "guid": entry.guid or "",
        "canonical_url": entry.canonical_url,
        "url": entry.url,
        "title": entry.title,
        "summary": entry.summary,
        "body": entry.body,
        "author": entry.author,
        "language": entry.language,
        "content_hash": entry.content_hash,
        "published_at": entry.published_at,
    }
    with connection.cursor() as cur:
        cur.execute(_INSERT, params)
        row = cur.fetchone()
        if row is not None:
            return UpsertResult(article_id=int(row[0]), inserted=True)
        cur.execute(_TOUCH_EXISTING, params)
        row = cur.fetchone()
    if row is None:  # pragma: no cover - the conflicting row was deleted in between
        raise RuntimeError(f"article conflict without a matching row (feed {feed_id})")
    return UpsertResult(article_id=int(row[0]), inserted=False)
