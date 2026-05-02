"""Article upsert with deduplication by (feed_id, guid) or content_hash."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import connection

from apps.articles.normalizer import NormalizedEntry


@dataclass(slots=True)
class UpsertResult:
    article_id: int
    inserted: bool


_UPSERT_BY_GUID = """
INSERT INTO articles_article
  (feed_id, guid, canonical_url, url, title, summary, body, author,
   language, content_hash, published_at, fetched_at, last_seen_at, is_deleted, created_at)
VALUES
  (%(feed_id)s, %(guid)s, %(canonical_url)s, %(url)s, %(title)s, %(summary)s, %(body)s, %(author)s,
   %(language)s, %(content_hash)s, %(published_at)s, now(), now(), false, now())
ON CONFLICT (feed_id, guid) WHERE guid <> ''
DO UPDATE SET last_seen_at = excluded.last_seen_at
RETURNING id, (xmax = 0) AS inserted;
"""

_UPSERT_BY_HASH = """
INSERT INTO articles_article
  (feed_id, guid, canonical_url, url, title, summary, body, author,
   language, content_hash, published_at, fetched_at, last_seen_at, is_deleted, created_at)
VALUES
  (%(feed_id)s, %(guid)s, %(canonical_url)s, %(url)s, %(title)s, %(summary)s, %(body)s, %(author)s,
   %(language)s, %(content_hash)s, %(published_at)s, now(), now(), false, now())
ON CONFLICT (content_hash)
DO UPDATE SET last_seen_at = excluded.last_seen_at
RETURNING id, (xmax = 0) AS inserted;
"""


def upsert_article(feed_id: int, entry: NormalizedEntry) -> UpsertResult:
    params = {
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
    sql = _UPSERT_BY_GUID if entry.guid else _UPSERT_BY_HASH
    with connection.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    article_id, inserted = row
    return UpsertResult(article_id=int(article_id), inserted=bool(inserted))
