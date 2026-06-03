# ADR-0004 — Dedup inside a feed: `(feed_id, guid)` first, then `(feed_id, content_hash)`

**Status:** accepted (revised: dedup was global by `content_hash` at first)

## Context

Articles re-appear within a feed: re-published with the same guid, or with a new guid but the
same content. Syndicated stories also appear in several feeds.

The first version kept a global unique index on `content_hash`, so two feeds carrying the
same story shared one row owned by whichever feed surfaced it first. That broke feed filters
in search and subscriptions (the story was invisible for the second feed), and an entry with
a guid whose content hash already existed elsewhere failed the insert with a unique violation.

## Decision

Two unique indexes, both scoped to the feed:

- `articles_feed_guid_uniq` on `(feed_id, guid) WHERE guid <> ''`;
- `articles_feed_hash_uniq` on `(feed_id, content_hash)`.

`upsert_article(...)` runs `INSERT ... ON CONFLICT DO NOTHING RETURNING id`. A returned id
is a real insert. Otherwise the entry is a duplicate of an existing row in the same feed —
matched by guid first, then by content hash — and only that row's `last_seen_at` is bumped.
The `article_created` signal (tag rules, instant subscriptions) fires on real inserts only.

## Consequences

- The same story in two feeds is stored twice, once per feed; each copy is found by its own
  feed filter. Search results may show both copies.
- A feed that drops `guid` mid-life does not create duplicates: the hash still matches.
- Under concurrent inserts of the same entry, `ON CONFLICT DO NOTHING` waits for the other
  transaction, so the follow-up lookup finds the committed row.
