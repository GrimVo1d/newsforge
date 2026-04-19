# ADR-0001 — Stored `tsvector` column with a `BEFORE INSERT/UPDATE` trigger

**Status:** accepted

## Context

We need full-text search across millions of articles, in multiple languages, with low latency.

## Decision

Store the `tsvector` as a physical column (`articles_article.tsv`), maintained by a `BEFORE INSERT OR UPDATE OF title, summary, body, language` trigger. Index it with a partial GIN: `WHERE NOT is_deleted`.

## Rejected alternatives

1. **`GENERATED ALWAYS AS ... STORED`** — requires `IMMUTABLE` expression. `to_tsvector(regconfig, ...)` is only `STABLE` (dictionaries are user-modifiable). PostgreSQL refuses to compile such a column.
2. **Compute at query time** (`to_tsvector(language, title || ...) @@ q`) — 30-50× slower at 1M rows. No GIN possible without an expression index, which loses query-flexibility.
3. **Expression index on `to_tsvector(...)`** — works for one regconfig only; we need per-row regconfig.

## Consequences

- Writes pay the cost of the trigger (one tsvector build per insert/update).
- The partial GIN keeps the index smaller and skips deleted articles during search.
- Migrating dictionaries requires an explicit `UPDATE` to rerun the trigger.
