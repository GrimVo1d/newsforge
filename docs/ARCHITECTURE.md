# Architecture

## Data flow

```
  Beat ── every 60 s ──> enqueue_due_feeds ──┐
                                             │  (queue: default)
                                             v
                                        fetch_feed ── robots.txt ─┐
                                             │                    │  apps.core.safe_http
                         per-domain lock ────┤  conditional GET ──┤  (pinned IP, redirects,
                         (Redis SET NX EX)   │                    │   deadline, size cap)
                                             v
                                        feedparser
                                             │  one task per entry (≤ MAX_ENTRIES_PER_FETCH)
                                             v
                                      process_article ── normalize ── upsert ──> PostgreSQL
                                             │                                   (tsv trigger)
                                             │  article_created (real inserts only)
                                             v
                          chain: apply_tag_rules ──> fanout_instant ──> deliver ── webhook
                                                                           │      └ email
  Beat ── 09:00 UTC ──> daily_digest ──────────────────────────────────────┘

  client ── HTTP ──> gunicorn / DRF ── SQL ──> PostgreSQL (FTS, pg_trgm)
```

## Code layout

```
src/newsforge/            settings (base, dev, test, prod), URLs, Celery app and beat schedule
src/apps/core/            auth endpoints, health and metrics, error envelope, pagination,
                          permissions, safe outbound HTTP client, PG extensions migration
src/apps/feeds/           Feed model and API, URL validator, fetcher, robots, rate limit, backoff
src/apps/articles/        Article model (tsv trigger in a migration), normalizer, upsert, API
src/apps/tags/            Tag / ArticleTag / TagRule models, rule engine, API
src/apps/search/          SearchView, parameter validation, raw SQL in queries/*.sql
src/apps/subscriptions/   Subscription / DeliveryLog models and API
src/tasks/                Celery tasks: scheduler, fetcher, articles, tags, notifications, digest
```

Raw SQL is used on purpose for the upsert, search and scheduling queries. Parameters always
go through psycopg placeholders; text-search configuration names come from a whitelist
(`apps.search.queries.coerce_lang`) or from the `language` column, which only ever holds
`russian`, `english` or `simple`.

## Components

### API

DRF with SimpleJWT bearer authentication only (no sessions, no admin site). Defaults:
`IsAuthenticatedOrReadOnly`, limit/offset pagination (`limit` up to 100), anonymous and
per-user throttles, and the error envelope `{"code": "...", "detail": ...}` from
`apps.core.exceptions.envelope`.

Shared data — feeds, tags, tag rules, article tags — is written by staff only
(`apps.core.permissions.IsStaffOrReadOnly`, `IsAdminUser` for tag rules). Subscriptions are
scoped to their owner in the queryset, so other users get `404`.

### Scheduling (`tasks.scheduler`)

`enqueue_due_feeds` selects up to 200 feeds with `next_fetch_at <= now()` that are active and
not paused, locking them with `FOR UPDATE SKIP LOCKED`, moves their `next_fetch_at` forward
by `interval_seconds`, commits, and queues one `fetch_feed` per feed. Concurrent Beat
instances cannot queue the same feed twice.

### Fetching (`tasks.fetcher`, `apps.feeds`)

1. **robots.txt** — `robots.is_allowed` fetches `/robots.txt` through the safe client
   (at most 200 KB, truncated beyond that), caches the body for 24 h in Redis and evaluates
   it with `urllib.robotparser`. A missing file or an unreachable host means "allowed"; a host
   that resolves to a private address means "disallowed".
2. **Rate limit** — `ratelimit.try_acquire` sets `rl:fetch:<host>` with `NX` and a TTL of
   `PER_DOMAIN_MIN_INTERVAL`; if the key exists the fetch is skipped until the next round.
3. **Conditional GET** — `If-None-Match` / `If-Modified-Since` from the stored validators.
   `304` → `not_modified`; other statuses ≥ 300 (after redirects) → `http_error`.
4. **Parsing** — `feedparser`; a UTF-8 BOM is stripped first. A malformed document with no
   entries → `parse_error`. On success the feed's title, site URL and validators are saved.
5. **Failures** — `consecutive_errors` grows, `next_fetch_at` is pushed out by
   `interval × 2^min(errors, 6) × jitter(0.5–1.5)`, and after 6 errors in a row the feed is
   paused for 24 hours (`disabled_until`).

### Safe outbound HTTP (`apps.core.safe_http`)

Feeds, robots.txt and webhooks all go through `safe_http.request`, which on every hop:
checks scheme (`https`, or `http` with `ALLOW_PLAIN_HTTP`), default port, no credentials in
the URL; resolves the host once and requires every address to be globally routable; then
connects to that exact address while sending the original `Host` header and TLS SNI, so
certificate verification still uses the hostname. Redirects are followed manually (up to 5,
none for webhooks) and each target goes through the same checks. An overall deadline covers
all hops and the body, and the body is read in chunks up to a byte limit. Proxy environment
variables are ignored. See [ADR-0003](ADR/0003-ssrf-guard.md).

### Normalization (`apps.articles.normalizer`)

- The entry link must be an absolute `http(s)` URL (at most 2048 characters), otherwise the
  entry is skipped.
- `canonicalize_url` lower-cases scheme and host, drops default ports, the fragment and
  tracking parameters (`utm_*`, `fbclid`, `gclid`, `yclid`, `mc_*`, `ref*`) and sorts the query.
- Title and author become plain text: tags stripped, entities decoded, whitespace collapsed.
- Summary and body are sanitized with a `bleach` whitelist (basic formatting, links, images,
  tables; `http`, `https` and `mailto` URLs only).
- `detect_language` uses `langdetect` with a fixed seed and maps `ru`/`en` to the `russian`/
  `english` configurations; short or unrecognized text becomes `simple`.
- `content_hash` is SHA-256 over the canonical URL, the title and the first 512 characters of
  the body (or the summary).

### Deduplication (`apps.articles.services`)

Two unique indexes, both per feed: `(feed_id, guid) WHERE guid <> ''` and
`(feed_id, content_hash)`. `upsert_article` inserts with `ON CONFLICT DO NOTHING`; on a
conflict it bumps `last_seen_at` on the existing row (the guid match wins over the hash
match). Only real inserts fire `article_created`. See [ADR-0004](ADR/0004-dedup-precedence.md).

### Full-text index

`articles_article.tsv` is maintained by a `BEFORE INSERT OR UPDATE OF title, summary, body,
language` trigger: title weight A, summary B, body C, each passed through `unaccent` and
`to_tsvector(language::regconfig, ...)`. A partial GIN index covers non-deleted rows; a
trigram GIN index on `title` serves the fuzzy fallback. See [ADR-0001](ADR/0001-tsvector-trigger.md),
[ADR-0002](ADR/0002-per-article-regconfig.md) and [SEARCH.md](SEARCH.md).

### Tag rules (`apps.tags.engine`)

Runs for every new article: each active rule (optionally limited to one language) checks its
keywords as case-insensitive substrings of title + summary + body; `any` needs one hit,
`all` needs every keyword. Matching tags are attached once.

### Subscriptions (`tasks.notifications`, `tasks.digest`)

- **instant** — `fanout_instant` runs after `apply_tag_rules` (a Celery chain) and selects
  subscriptions whose query matches the article (parsed in the article's language) and whose
  `feeds` / `tag_ids` filters, if set, include it.
- **daily** — `daily_digest` at 09:00 UTC matches articles created since the subscription's
  previous run (or the last 24 h), newest first, at most 100 per subscription.
- **deliver** — skips pairs already delivered successfully; sends a signed webhook
  (`X-NF-Timestamp`, `X-NF-Signature: sha256=HMAC(secret, "<ts>." + body)`,
  `X-Idempotency-Key`) or an email; records every attempt in `subscriptions_deliverylog`
  (one row per subscription and article, with `attempts`, `succeeded`, `http_status`,
  `error`). Retries: up to 5 with exponential backoff for `5xx`, `408`, `429`, network and
  SMTP errors. See [ADR-0005](ADR/0005-at-least-once-delivery.md).

## Celery

Tasks have explicit names (`tasks.<module>.<name>`) and are routed by module:

| Queue | Tasks |
|---|---|
| `default` | `tasks.fetcher.*`, `tasks.articles.*`, `tasks.tags.*`, `tasks.notifications.*`, `enqueue_due_feeds` (from Beat) |
| `low` | `tasks.digest.*`, `tasks.scheduler.*` (except the Beat-scheduled `enqueue_due_feeds`) |

The compose worker consumes both queues with concurrency `CELERY_CONCURRENCY` (default 4).
Workers run with `acks_late`, prefetch multiplier 1 and soft/hard time limits of 60/90 s
(see [ADR-0006](ADR/0006-celery-acks-late-prefetch.md)).

Beat schedule (`newsforge/celery.py`, UTC):

| Entry | Task | When |
|---|---|---|
| `enqueue-due-feeds` | `tasks.scheduler.enqueue_due_feeds` | every 60 s |
| `daily-digest` | `tasks.digest.daily_digest` | 09:00 daily |
| `refresh-robots-cache` | `tasks.scheduler.refresh_robots_cache` | 04:00 daily (drops cached robots.txt) |
| `cleanup-old-articles` | `tasks.scheduler.cleanup_old_articles` | Sunday 03:00 (soft-deletes articles published over 365 days ago) |

## Operations endpoints

- `/health/live` — process is up.
- `/health/ready` — `SELECT 1` and a Redis `PING`; `503` if either fails.
- `/metrics` — Prometheus exposition of the default process and Python collectors; answers
  `404` unless `METRICS_TOKEN` is set and sent as a bearer token.
