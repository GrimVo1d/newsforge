# ADR-0004 — Dedup precedence: `(feed_id, guid)` first, then `content_hash`

**Status:** accepted

## Context

Articles can re-appear within a feed (re-pub with same guid) or across feeds (syndication with different guids but the same content).

## Decision

`upsert_article(...)` picks the conflict target by whether `guid` is present:

1. `guid != ''` → `INSERT ... ON CONFLICT (feed_id, guid) WHERE guid <> '' DO UPDATE SET last_seen_at = excluded.last_seen_at`.
2. `guid == ''` → fallback to `INSERT ... ON CONFLICT (content_hash)`.

In both cases the conflict updates only `last_seen_at`. We return `(xmax = 0) AS inserted` to distinguish real inserts from updates — used by the receiver of `article_created` to fan out tag-rule and notification work only on real inserts.

## Consequences

- Two feeds republishing the same article share one DB row (deduped by `content_hash`), with `last_seen_at` bumped on each ingest. The `feed_id` stored on that row is the first feed that surfaced it.
- A feed that drops `guid` mid-life will create duplicates only on the transition (guid-keyed rows stay, hash-keyed new rows added). Acceptable.
