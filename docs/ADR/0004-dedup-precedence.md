# ADR-0004 — Dedup inside a feed: `(feed_id, guid)` first, then `(feed_id, content_hash)`

**Status:** accepted (revised: dedup was global by `content_hash` at first; edited entries
were not updated and the hash covered only the first 512 characters of the body)

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
is a real insert. Otherwise the entry is a duplicate of an existing row in the same feed:

- same guid, different content hash, and no other row of the feed has the new hash → the
  entry was edited at the source; the row gets the new title, text, URL and hash;
- otherwise (matched by guid first, then by content hash) only that row's `last_seen_at` is
  bumped.

The content hash covers the canonical URL, the title and the whole body (or summary), so
entries that share a long boilerplate start are not merged.

Tagging and instant subscriptions are queued once per article: the first `process_article`
to set `processed_at` on the row queues them. If queueing fails, `processed_at` is reset, so
a retry or a redelivered task (`acks_late`) still queues them, even though the row exists.

## Consequences

- The same story in two feeds is stored twice, once per feed; each copy is found by its own
  feed filter. Search results may show both copies.
- A feed that drops `guid` mid-life does not create duplicates: the hash still matches.
- An edit is not announced again: subscribers were notified about the article already, and
  tag rules are not re-run on it.
- An edit that collides with another row's content keeps both rows unchanged.
- Under concurrent inserts of the same entry, `ON CONFLICT DO NOTHING` waits for the other
  transaction, so the follow-up lookup finds the committed row.
