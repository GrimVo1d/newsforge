"""Article upsert with deduplication inside a feed, by guid or by content_hash.

Both keys are unique per feed (``articles_feed_guid_uniq``, ``articles_feed_hash_uniq``), so
the same story in two feeds is stored twice, once per feed. An insert that hits either key
is a duplicate: an entry with the same guid but new content is updated in place (unless
another row of the feed already has that content), any other duplicate only gets its
``last_seen_at`` bumped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, connection, transaction

from apps.articles.normalizer import NormalizedEntry


@dataclass(slots=True)
class UpsertResult:
    article_id: int
    inserted: bool
    updated: bool = False


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

# The entry was edited at the source: same guid, new content.
_UPDATE_EDITED = """
UPDATE articles_article
SET canonical_url = %(canonical_url)s, url = %(url)s, title = %(title)s,
    summary = %(summary)s, body = %(body)s, author = %(author)s, language = %(language)s,
    content_hash = %(content_hash)s, published_at = coalesce(%(published_at)s, published_at),
    last_seen_at = now()
WHERE feed_id = %(feed_id)s AND %(guid)s <> '' AND guid = %(guid)s
  AND content_hash <> %(content_hash)s
  AND NOT EXISTS (
    SELECT 1 FROM articles_article
    WHERE feed_id = %(feed_id)s AND content_hash = %(content_hash)s
  )
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

_CLAIM = """
UPDATE articles_article SET processed_at = now()
WHERE id = %(id)s AND processed_at IS NULL
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
        try:
            with transaction.atomic():
                cur.execute(_UPDATE_EDITED, params)
                row = cur.fetchone()
        except IntegrityError:  # another row got this content concurrently
            row = None
        if row is not None:
            return UpsertResult(article_id=int(row[0]), inserted=False, updated=True)
        cur.execute(_TOUCH_EXISTING, params)
        row = cur.fetchone()
    if row is None:  # pragma: no cover - the conflicting row was deleted in between
        raise RuntimeError(f"article conflict without a matching row (feed {feed_id})")
    return UpsertResult(article_id=int(row[0]), inserted=False)


def claim_processing(article_id: int) -> bool:
    """Mark the article as processed; True only for the one caller that does it first."""
    with connection.cursor() as cur:
        cur.execute(_CLAIM, {"id": article_id})
        return cur.fetchone() is not None


def release_processing(article_id: int) -> None:
    """Undo claim_processing after queueing failed, so a retry processes the article."""
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE articles_article SET processed_at = NULL WHERE id = %(id)s;",
            {"id": article_id},
        )
