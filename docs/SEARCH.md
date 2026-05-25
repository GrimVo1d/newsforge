# SEARCH — newsforge

## Ranking weights

A/B/C are assigned at index time via `setweight` and reused at query time via the optional `weights` argument to `ts_rank_cd`. We use defaults (`{0.1, 0.2, 0.4, 1.0}` for `{D, C, B, A}`).

| Weight | Field | Rationale |
|---|---|---|
| A (1.0) | title | strongest intent signal for news |
| B (0.4) | summary | dense, hand-written; still ranks high |
| C (0.2) | body | longest and noisiest |
| D | unused | reserved for future |

Normalization mask: `32` (divide rank by `1 + log(doc_length)`). Without it long bodies dominate. We picked 32 over the more aggressive 1+2 because cover density already discounts spread terms.

## Language configs

| `language` | regconfig |
|---|---|
| `russian`, `ru` | `russian` |
| `english`, `en` | `english` |
| anything else / empty | `simple` |

The `simple` config does no stemming and no stop-word removal — it is the fall-through for unsupported languages and very short input. We never interpolate the language string into SQL directly; `apps.search.queries.coerce_lang()` whitelists.

## Highlighting (`ts_headline`)

Parameters used:

```
MaxFragments=2, MinWords=5, MaxWords=20, StartSel=<b>, StopSel=</b>
```

`MaxFragments=2` keeps the response payload bounded. Highlighting is the most expensive operator in the query and runs only over the LIMITed result page — never as a filter.

## Fuzzy fallback (`pg_trgm`)

When `websearch_to_tsquery` yields 0 rows AND `len(q) <= 24`, the client may fall back to:

```sql
SELECT id, title, similarity(title, $1) AS sim
FROM articles_article
WHERE NOT is_deleted AND title %% $1
ORDER BY sim DESC
LIMIT 20;
```

This catches misspellings ("djnago" → "django"). Threshold via the `pg_trgm.similarity_threshold` GUC.

## Adding a new language

1. `CREATE TEXT SEARCH CONFIGURATION <name> ( COPY = pg_catalog.simple );` then `ALTER` to wire the appropriate dict.
2. Drop stopword / synonym files into PG `$SHAREDIR/tsearch_data/`.
3. Add the regconfig name to `apps.search.queries.SUPPORTED_LANGS`.
4. (Optional) backfill: `UPDATE articles_article SET language='<name>' WHERE feed_id IN (...);` — the BEFORE-UPDATE trigger reindexes affected rows.

## Why a trigger and not `GENERATED ALWAYS`

`GENERATED ALWAYS AS ... STORED` requires the expression to be `IMMUTABLE`. `to_tsvector(regconfig, ...)` is `STABLE` (dictionaries can be updated). PG rejects the column. The trigger pattern keeps the column physically present and refreshed on relevant updates, while letting us pick the regconfig per row from `language`.
