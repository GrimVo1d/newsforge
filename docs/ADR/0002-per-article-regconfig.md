# ADR-0002 — Per-article `regconfig`

**Status:** accepted

## Context

The corpus is mixed: Russian and English (and occasional everything else). A single tsvector configuration is a poor fit — Russian stemming on English text destroys recall, and vice versa.

## Decision

Each article stores a `language` column (`russian` / `english` / `simple`). The trigger picks the regconfig per row when building `tsv`. The search endpoint does the same per request, taking `lang` from the query string. Unknown / missing languages fall back to `simple`.

`apps.search.queries.coerce_lang()` whitelists the allowed regconfigs — user input is never interpolated as a regconfig name.

## Rejected alternatives

- **Single `simple` config everywhere** — loses Russian stemming, ranking becomes useless on RU content.
- **`pg_dict_int` / `pg_catalog.default`** — neither covers our mix.

## Consequences

- Articles cannot mix two languages in a single tsvector cell — acceptable since articles are mono-lingual.
- Adding a new language is a 3-step procedure (`docs/SEARCH.md` has the recipe).
- Search clients should pass `lang` when known; we auto-detect via `langdetect` at ingest, with `DetectorFactory.seed=0` for determinism.
