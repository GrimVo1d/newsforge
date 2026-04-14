# ARCHITECTURE — newsforge

## Data flow

```
                 ┌──────────────┐
                 │    Beat      │  every minute
                 └──────┬───────┘
                        │ enqueue_due_feeds
                        v
   ┌────────────────────────────────────┐
   │  Redis (broker + rate-limit)       │
   └──┬─────────────────────────────────┘
      │
      v fetch_feed                     v process_article
   ┌────────┐  HTTPS + ETag      ┌─────────────────┐  upsert
   │ Worker │ ─────────────────> │  feedparser /   │ ───────> Postgres (articles)
   │        │ <─── 200/304 ───── │  normalizer     │
   └────────┘                    └─────────────────┘
                                          │
                                          v on_new_article
                                  ┌─────────────────┐
                                  │ apply_tag_rules │  ── set tags ──> Postgres
                                  └─────────────────┘
                                          │
                                          v
                                ┌────────────────────┐
                                │ notify_subscriber  │ ── webhook / email
                                └────────────────────┘

   client ─HTTP→ API (DRF) ─SQL→ Postgres (tsvector search)
```

## Components

### API (`apps/{feeds,articles,search,tags,subscriptions}/views.py`)
- DRF ViewSets for CRUD-style resources.
- `SearchView` is an `APIView`, not a ViewSet; uses raw SQL for `ts_rank_cd` and `ts_headline`.

### Search query (canonical SQL)

```sql
WITH q AS (
  SELECT websearch_to_tsquery(%(cfg)s::regconfig, unaccent(%(query)s)) AS tsq
)
SELECT
    a.id, a.title, a.summary, a.url, a.feed_id, a.published_at, a.language,
    ts_rank_cd(a.tsv, q.tsq, 32) AS rank,
    ts_headline(%(cfg)s::regconfig, coalesce(a.summary, ''), q.tsq,
        'MaxFragments=2, MinWords=5, MaxWords=20, StartSel=<b>, StopSel=</b>'
    ) AS highlight
FROM articles_article a, q
WHERE NOT a.is_deleted
  AND a.tsv @@ q.tsq
  AND (%(from)s IS NULL OR a.published_at >= %(from)s)
  AND (%(to)s   IS NULL OR a.published_at <  %(to)s)
  AND (cardinality(%(feeds)s::bigint[]) = 0 OR a.feed_id = ANY(%(feeds)s))
ORDER BY rank DESC, a.published_at DESC
LIMIT %(limit)s OFFSET %(offset)s;
```

### Feed fetcher (`apps/feeds/fetcher.py`)
- `httpx` client with timeout and streaming size cap.
- Sends `If-None-Match` / `If-Modified-Since` from DB.
- On 304: update `last_fetched_at`, status `not_modified`, return.
- On 200: store new ETag / Last-Modified, hand body to `feedparser`.
- If response exceeds `MAX_RESPONSE_BYTES` → abort stream, mark `last_status='too_large'`.
- Concurrency is the Celery worker pool + per-domain Redis rate limit.

### Robots policy (`apps/feeds/robots.py`)
- `is_allowed(url) -> bool` reads `https://<host>/robots.txt`, 24h Redis cache.
- On disallow: `last_status='robots_blocked'`, feed is not polled.

### Normalizer (`apps/articles/normalizer.py`)
- `bleach.clean(html, allowed_tags=[...], strip=True)` for sanitization.
- `canonicalize_url(url)` — drop UTM, drop fragment, normalize host.
- `content_hash(article) -> sha256` — deterministic.
- `detect_language(text) -> str` — `langdetect` with `DetectorFactory.seed=0`; fallback `simple`.

### Dedup (`apps/articles/services.py`)
1. If `guid` present: upsert on `(feed_id, guid)`.
2. Otherwise: upsert on `(content_hash)`.
3. On conflict: bump `last_seen_at`, no duplicate row.

### Tag rules engine (`apps/tags/engine.py`)
- Triggered async on every new article via signal.
- All active rules of the article-owner space → keyword check (case-insensitive substring) against title + summary + body.
- `match='any'` — at least one keyword; `match='all'` — all of them.

### Subscriptions matcher (`apps/subscriptions/services.py`)
- `interval='instant'` — on every new article, evaluate matching subscriptions: `tsv @@ websearch_to_tsquery(q)` plus optional feed/tag filters.
- `interval='daily'` — Beat task aggregates last 24h.

### Notifications
- Webhook: `httpx.post(url, json=payload, headers={"X-NF-Signature": hmac_sha256, "X-Idempotency-Key": <key>})`. 10s timeout.
- Email: SMTP via `django.core.mail` (mailpit in dev).
- Result recorded in `delivery_log` (`UNIQUE (subscription_id, article_id)` enforces idempotency).

## Beat schedule

```python
CELERY_BEAT_SCHEDULE = {
    "enqueue-due-feeds": {"task": "tasks.enqueue_due_feeds", "schedule": 60.0},
    "daily-digest":      {"task": "tasks.daily_digest", "schedule": crontab(hour=9, minute=0)},
    "refresh-robots":    {"task": "tasks.refresh_robots_cache", "schedule": crontab(hour=4, minute=0)},
    "cleanup-old":       {"task": "tasks.cleanup_old_articles", "schedule": crontab(day_of_week=0, hour=3)},
}
```

## Queues

| Name | concurrency | purpose |
|---|---|---|
| `default` | 16 | `fetch_feed`, `process_article`, `apply_tag_rules`, `notify_subscriber_instant` |
| `low` | 2 | `daily_digest`, `cleanup_old_articles`, `refresh_robots_cache` |

Worker config: `task_acks_late=True`, `worker_prefetch_multiplier=1`, visibility timeout 600s — so a 30s `fetch_feed` doesn't starve fast tasks queued behind it.

## Performance notes

- `articles_article.tsv` is a single column with A/B/C weights; partial GIN index `WHERE NOT is_deleted`. Sub-second search over 1M rows.
- `ts_headline` is the most expensive operator — call it only over the LIMITed result page.
- Pagination in search: offset on the first pages, keyset (`ORDER BY rank DESC, id DESC`) on deep pages.
- BRIN index on `fetched_at` for historic range scans.

## Security

- SSRF guard on `POST /feeds/`: scheme check, DNS resolution, reject if any resolved IP is private/loopback/link-local/multicast/reserved; same check inside the fetcher (TOCTOU mitigation).
- HTML sanitization is mandatory before persistence.
- Webhook payloads HMAC-signed; receivers can dedupe on `X-Idempotency-Key`.
- Auth: SimpleJWT (access + refresh). Public read for feeds/articles/search.
