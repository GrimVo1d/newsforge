# Search

## API

`GET /api/v1/search/` — public, throttled (`THROTTLE_SEARCH`, 60 requests per minute by
default, on top of the anonymous / per-user limits).

| Parameter | Default | Values |
|---|---|---|
| `q` | — | up to 256 characters, web-search syntax (below); empty → empty result |
| `lang` | `simple` | `russian` / `ru`, `english` / `en`, `simple` — how `q` is parsed |
| `sort` | `rank` | `rank` (relevance, then newest) or `date` (newest first, no snippets) |
| `feed` | all | feed ids: `feed=1&feed=2` or `feed=1,2`, at most 50 |
| `from`, `to` | — | ISO 8601 datetimes, `from <= published_at < to` |
| `limit` | 20 | 1–100 |
| `offset` | 0 | 0–10000 |

Invalid parameters give `400` with `{"code": "validation_error", "detail": {...}}`.

Response: `{"count": <hits on this page>, "results": [...]}`; each hit has `id`, `title`,
`summary`, `url`, `feed_id`, `published_at`, `language`, `rank` and `highlight`. `count` is the
size of the returned page, not the total number of matches: to page through results, request
the next `offset` until a page comes back shorter than `limit`. Articles of deleted feeds are
never returned.

Query syntax (`websearch_to_tsquery`): words are AND-ed, `"quoted phrase"`, `or`, and `-word`
to exclude. `unaccent` is applied to both the query and the index, so `café` matches `cafe`.

Pass `lang` matching the content you are looking for: a Russian query parsed with `simple`
does not stem, so `обновления` will not match `обновление`.


## Ranking weights

A/B/C are assigned at index time via `setweight`. `ts_rank_cd` is called without a `weights`
argument, so it applies the default weights `{0.1, 0.2, 0.4, 1.0}` for `{D, C, B, A}`.

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
| `simple` / not given | `simple` |

Each article stores the configuration it was indexed with (detected at ingest). Subscriptions
parse their query in the language of each candidate article.

The `simple` config does no stemming and no stop-word removal — it is the fall-through for unsupported languages and very short input. We never interpolate the language string into SQL directly; `apps.search.queries.coerce_lang()` whitelists.

## Highlighting (`ts_headline`)

Parameters used:

```
MaxFragments=2, MinWords=5, MaxWords=20, StartSel=<b>, StopSel=</b>
```

`MaxFragments=2` keeps the response payload bounded. Highlighting is the most expensive
operator in the query, so `search_rank.sql` computes it in an outer query over the already
limited page. Its input is the summary with all tags removed (cut to 2000 characters), so the
snippet is plain text, HTML-escaped (`&amp;`, `&lt;`), whose only markup is the `<b>` marks.
It is safe to render as HTML.

## Fuzzy fallback (`pg_trgm`)

When the full-text query finds nothing and `q` is at most 24 characters, the endpoint
answers from `queries/trgm_fallback.sql` instead: trigram similarity of `q` against titles
(`title % q`, served by the `articles_title_trgm_idx` GIN index), with the same `feed`,
`from`, `to`, `limit` and `offset` filters. `rank` is then the similarity (0–1) and
`highlight` is empty. Paging past the last full-text hit (`offset` beyond the matches) returns
an empty page, not fuzzy results.

This catches misspellings ("djnago" → "django"). The cut-off is the
`pg_trgm.similarity_threshold` setting (0.3 by default).

## Adding a new language

1. `CREATE TEXT SEARCH CONFIGURATION <name> ( COPY = pg_catalog.simple );` then `ALTER` to wire the appropriate dict.
2. Drop stopword / synonym files into PG `$SHAREDIR/tsearch_data/`.
3. Add the regconfig name to `apps.search.queries.SUPPORTED_LANGS` (and a short alias to
   `LANG_ALIASES`, if any), to `LANG_CHOICES` in
   `apps.search.serializers`, to `apps.feeds.models.Language`, and map its langdetect code in
   `apps.articles.normalizer._SUPPORTED_LANGS`.
4. (Optional) backfill: `UPDATE articles_article SET language='<name>' WHERE feed_id IN (...);` — the BEFORE-UPDATE trigger reindexes affected rows.

## Why a trigger and not `GENERATED ALWAYS`

`GENERATED ALWAYS AS ... STORED` requires the expression to be `IMMUTABLE`. `to_tsvector(regconfig, ...)` is `STABLE` (dictionaries can be updated). PG rejects the column. The trigger pattern keeps the column physically present and refreshed on relevant updates, while letting us pick the regconfig per row from `language`.
