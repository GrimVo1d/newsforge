# newsforge

RSS/Atom aggregator with PostgreSQL full-text search (`tsvector` + GIN), periodic polite polling via Celery Beat, and a REST API for browsing, search, manual/automatic tagging, and saved-query subscriptions (webhook or email).

## What this demonstrates

- Periodic background work (Celery Beat) with polite outbound HTTP (ETag / If-Modified-Since, robots.txt, per-domain rate limit, exponential backoff).
- Full-text search on PostgreSQL only — no external Elasticsearch — using `tsvector`, partial GIN, `websearch_to_tsquery`, `ts_rank_cd`, `ts_headline`, language-aware regconfigs.
- Classic ingest pipeline: fetch → parse → normalize → deduplicate → enrich (tags).
- SSRF-safe URL ingestion, idempotent upserts, at-least-once delivery with receiver-side dedup.

## Stack

Python 3.12 · Django 5 · DRF · PostgreSQL 16 · Redis 7 · Celery 5 · Docker · GitHub Actions

## Quickstart

```bash
cp .env.example .env
docker compose up -d
docker compose exec api python manage.py migrate
docker compose exec api python manage.py loaddata initial_feeds.json
docker compose exec worker celery -A newsforge inspect ping
# API:     http://localhost:8000/api/v1/
# OpenAPI: http://localhost:8000/api/schema/swagger-ui/
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — components and data flow
- [docs/ADR/](docs/ADR/) — architectural decisions
- [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md), [docs/RUNBOOK.md](docs/RUNBOOK.md), [docs/PERFORMANCE.md](docs/PERFORMANCE.md), [docs/SEARCH.md](docs/SEARCH.md), [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — operational guides
