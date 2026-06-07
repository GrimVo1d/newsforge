# newsforge

RSS/Atom aggregator with PostgreSQL full-text search. Celery Beat polls feeds politely, new
entries are normalized, deduplicated and indexed with a trigger-maintained weighted
`tsvector`, and a REST API serves articles, search, tags and saved-query subscriptions
delivered by signed webhook or email.

## Features

- **Polite crawling** — conditional requests (ETag / If-Modified-Since), robots.txt with a
  24 h cache, a per-domain rate limit in Redis, exponential backoff and temporary disabling
  of failing feeds.
- **Safe outbound HTTP** — feed, robots.txt and webhook URLs must resolve to public
  addresses; connections are pinned to the checked IP, redirects are re-checked on every hop,
  and every request has a deadline and a size cap.
- **Ingest pipeline** — fetch → parse (`feedparser`) → normalize (plain-text titles,
  `bleach`-sanitized HTML, canonical URLs, language detection) → deduplicate per feed by
  guid or content hash → auto-tag by keyword rules → notify subscribers.
- **Full-text search in PostgreSQL only** — weighted `tsvector` (title > summary > body),
  per-article Russian / English / simple configuration, `websearch_to_tsquery` syntax,
  `ts_rank_cd` ranking, `ts_headline` snippets and a `pg_trgm` fallback for typos.
- **Subscriptions** — a saved query with optional feed and tag filters, delivered instantly
  or as a daily batch, by HMAC-SHA256-signed webhook or by email, with retries and a
  per-delivery log.
- **API** — DRF with JWT auth, OpenAPI schema and Swagger UI, throttling, a uniform error
  envelope `{"code": ..., "detail": ...}`.

## Stack

Python 3.12 · Django 5.2 LTS · Django REST framework · SimpleJWT · drf-spectacular ·
Celery 5 · PostgreSQL 16 (`unaccent`, `pg_trgm`) · Redis 7 · httpx · Docker Compose

## Quick start

Requires Docker with Compose v2.

```bash
cp .env.example .env          # optional: every value has a dev default
make up                       # build and start db, redis, mailpit, migrate, api, worker, beat
make superuser                # staff account: only staff may add feeds, tags and tag rules
```

- API: <http://localhost:8000/api/v1/>
- Swagger UI: <http://localhost:8000/api/schema/swagger-ui/>
- Mailpit (captured subscription emails): <http://localhost:8025/>

[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) walks through adding a feed, searching
and setting up a subscription.

## API at a glance

All paths are under `/api/v1/`. Reads are public unless noted; writes need
`Authorization: Bearer <access token>`.

| Endpoint | Methods | Who |
|---|---|---|
| `auth/register/`, `auth/token/`, `auth/token/refresh/` | POST | anyone (throttled) |
| `feeds/`, `feeds/{id}/` | GET; POST, PATCH, PUT, DELETE | read: anyone; write: staff |
| `feeds/{id}/refresh/` | POST | staff |
| `articles/`, `articles/{id}/` | GET | anyone |
| `articles/{id}/tags/` | POST, DELETE | staff |
| `search/` | GET | anyone (throttled) |
| `tags/`, `tags/{id}/` | GET; POST, PATCH, PUT, DELETE | read: anyone; write: staff |
| `tag-rules/`, `tag-rules/{id}/` | all | staff |
| `subscriptions/`, `subscriptions/{id}/` | all | owner |
| `subscriptions/{id}/rotate-secret/` | POST | owner |
| `subscriptions/{id}/deliveries/` | GET | owner |

Outside `/api/v1/`: `/api/schema/` (OpenAPI), `/health/live`, `/health/ready` and
`/metrics` (Prometheus, only with `Authorization: Bearer $METRICS_TOKEN`).

## Development

Tests, linters and type checks run in the `dev` container against the compose database:

```bash
make test         # pytest (unit + integration, needs PostgreSQL and Redis from compose)
make lint         # ruff check + ruff format --check
make typecheck    # mypy --strict
make check        # all three
make help         # every target
```

## Documentation

- [Getting started](docs/GETTING_STARTED.md) — first run, first feed, first subscription
- [Architecture](docs/ARCHITECTURE.md) — components, data flow, tasks and queues
- [Search](docs/SEARCH.md) — query syntax, ranking, languages, fuzzy fallback
- [Deployment](docs/DEPLOYMENT.md) — configuration reference and production settings
- [Threat model](docs/THREAT_MODEL.md), [Runbook](docs/RUNBOOK.md),
  [Performance](docs/PERFORMANCE.md)
- [Architecture decision records](docs/ADR/)
