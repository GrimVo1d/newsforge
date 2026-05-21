# PERFORMANCE — newsforge

Latency targets and the math behind them. Capacity is bottlenecked by Postgres FTS, not by Django.

## SLO

| Metric | Target |
|---|---|
| `GET /api/v1/search/` P95 (1M articles, single-word query) | < 200 ms |
| `GET /api/v1/articles/` (page 50) P95 | < 100 ms |
| `GET /api/v1/feeds/` P95 | < 80 ms |
| 500 feeds polled per beat iteration (worker concurrency 16) | < 5 min |
| MV / index drift | 0 (no MVs; trigger maintains tsv inline) |

## EXPLAIN shapes to expect

### Search (rank, with filters)

```
Limit  (cost=... rows=20 width=...)
  -> Sort  (rank DESC, published_at DESC NULLS LAST)
       Sort Key: ...
       -> Nested Loop
            -> CTE Scan on q
            -> Bitmap Heap Scan on articles_article a
                 Recheck Cond: (tsv @@ q.tsq)
                 Filter: (NOT is_deleted)
                 -> Bitmap Index Scan on articles_tsv_idx
                      Index Cond: (tsv @@ q.tsq)
Execution Time: 5-150 ms
```

A `Seq Scan on articles_article` here means the index is missing or `pg_stat_user_indexes` shows zero hits — check trigger health.

### Due feeds (beat scheduler)

```
LockRows
  -> Limit
       -> Index Scan using feeds_due_partial_idx on feeds_feed
            Index Cond: (next_fetch_at <= now())
Execution Time: < 1 ms
```

### `pg_trgm` fallback

```
Limit
  -> Sort  (rank DESC)
       -> Bitmap Heap Scan on articles_article
            -> Bitmap Index Scan on articles_title_trgm_idx
                 Index Cond: (title %% $1)
Execution Time: 5-50 ms
```

## Capacity math (4 CPU / 8 GB node)

```
T_search ≈ T_django + T_pg_fts + T_serialize
        ≈ 5 ms + 30 ms (typical GIN + ts_rank_cd + ts_headline) + 5 ms
        ≈ 40 ms
```

4 sync gunicorn workers → ~100 req/s for `/search/` per node.
List endpoints (no FTS) → ~250 req/s.

## What we deliberately don't optimize

- **Per-row serialization** — Django REST defaults are fine at our P95.
- **Connection pooling in app** — PG `CONN_MAX_AGE>0` is enough up to ~5 nodes. Add pgbouncer past that.
- **Caching individual articles in Redis** — they're index hits already; caching costs more than the lookup.
- **`ts_headline` on the whole result set** — we only call it on the `LIMIT`ed page; never as a filter.

## Tunables

| Setting | Default | When to change |
|---|---|---|
| `PER_DOMAIN_MIN_INTERVAL` | 30s | Increase if a provider complains, decrease (carefully) for very fresh feeds. |
| `MAX_RESPONSE_BYTES` | 5 MB | Raise if you ingest video / podcast feeds. |
| `worker_prefetch_multiplier` | 1 | Increase only after eliminating long-tail fetch tasks. |
| BRIN `pages_per_range` | 32 | Lower for finer-grained scans (more disk). |

## Scaling checklist

1. **pgbouncer** in front of PG past ~5 nodes.
2. **Read replica** for search; reports tolerate replica lag.
3. **Partition `articles_article`** by `published_at` monthly past 50M rows.
4. **Async DRF views** for `/search/` only past 500 RPS/node (requires asyncpg).
