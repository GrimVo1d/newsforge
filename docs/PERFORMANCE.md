# Performance

Where the time goes, which indexes serve which query and what to look at in `EXPLAIN`. The
latency figures below are design targets and rough estimates, not results of a benchmark in
this repository.

## Targets

| Request | Target P95 |
|---|---|
| `GET /api/v1/search/` (1M articles, one-word query, page of 20) | < 200 ms |
| `GET /api/v1/articles/` (page of 50) | < 100 ms |
| `GET /api/v1/feeds/` | < 80 ms |
| one Beat round of 200 due feeds (worker concurrency 16, many hosts) | < 5 min |

## Indexes

| Index | Serves |
|---|---|
| `articles_tsv_idx` — GIN on `tsv`, partial `WHERE NOT is_deleted` | full-text search, subscription matching |
| `articles_title_trgm_idx` — GIN `gin_trgm_ops` on `title`, partial `WHERE NOT is_deleted` | fuzzy fallback (`title % q`, `title %> q`) |
| `articles_pub_idx` — `(published_at DESC NULLS LAST, id DESC)` | `/articles/` listing, `sort=date` |
| `articles_feed_pub_idx` — `(feed_id, published_at DESC NULLS LAST, id DESC)` | `/articles/?feed=` |
| `articles_feed_guid_uniq`, `articles_feed_hash_uniq` — unique | dedup on insert |
| `feeds_due_basic_idx` — `next_fetch_at` | `enqueue_due_feeds` |
| `delivery_log_unique` — `(subscription_id, article_id)` | delivery dedup and log updates |

## EXPLAIN shapes to expect

### Search, `sort=rank`

```
Sort  (rank DESC, published_at DESC, id DESC)          -- outer query: ts_headline per row
  -> Nested Loop
       -> CTE Scan on q
       -> Limit
            -> Sort  (rank DESC, ...)
                 -> Bitmap Heap Scan on articles_article a
                      Recheck Cond: (tsv @@ q.tsq)
                      -> Bitmap Index Scan on articles_tsv_idx
```

`ts_headline` must appear only above the `Limit`. A `Seq Scan on articles_article` under the
inner sort means the GIN index is not used — check that the query has `NOT a.is_deleted`
(the index is partial) and that `ANALYZE` has run.

Broad queries ("news") match a large share of the table; ranking then has to score every
match before the `Limit`. That is the main cost driver, not the page size.

### Due feeds

```
LockRows
  -> Limit
       -> Sort (next_fetch_at)
            -> Index Scan using feeds_due_basic_idx on feeds_feed
                 Index Cond: (next_fetch_at <= now())
                 Filter: (is_active AND NOT is_deleted AND ...)
```

### Fuzzy fallback

```
Limit
  -> Sort (rank DESC, published_at DESC, id DESC)
       -> Bitmap Heap Scan on articles_article a
            -> BitmapOr
                 -> Bitmap Index Scan on articles_title_trgm_idx
                      Index Cond: (title % 'kubernets')
                 -> Bitmap Index Scan on articles_title_trgm_idx
                      Index Cond: (title %> 'kubernets')
```

## Rough capacity (4 CPU / 8 GB node)

```
T_search ≈ T_django + T_pg_fts + T_serialize
         ≈ 5 ms + 30 ms (GIN + ts_rank_cd + ts_headline on one page) + 5 ms
         ≈ 40 ms
```

With 4 sync gunicorn workers that is about 100 search requests per second per node; list
endpoints without FTS should manage about twice that.

## Deliberately not optimized

- **Serialization** — plain DRF serializers; the listing prefetches tags in one query.
- **Connection pooling** — none in the app; add pgbouncer when the number of processes grows.
- **Caching search results** — queries are too varied for a cache to pay off.
- **Total counts in search** — `count` is the page size, which avoids a second full scan of
  all matches.

## Tunables

| Setting | Default | When to change |
|---|---|---|
| `PER_DOMAIN_MIN_INTERVAL` | 30 s | raise if a provider complains; lower carefully for hosts with many feeds |
| `MAX_RESPONSE_BYTES` | 5 MB | raise for very large feeds |
| `MAX_ENTRIES_PER_FETCH` | 200 | entries beyond it are ignored on that fetch |
| `GUNICORN_WORKERS`, `CELERY_CONCURRENCY` | 4, 4 | per CPU and per number of distinct feed hosts |
| `worker_prefetch_multiplier` | 1 | keep at 1 while fetches dominate (ADR-0006) |
| `pg_trgm.similarity_threshold`, `pg_trgm.word_similarity_threshold` | 0.3, 0.6 | lower for more fuzzy matches, higher for fewer |
