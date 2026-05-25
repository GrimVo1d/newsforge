# DEPLOYMENT — newsforge

## Container stack

| Container | Image | Purpose |
|---|---|---|
| `api` | local build | gunicorn + Django |
| `worker` | local build | Celery worker (queues: `default`, `low`) |
| `beat` | local build | Celery beat scheduler |
| `db` | `postgres:16.2-alpine` | primary DB |
| `redis` | `redis:7.2-alpine` | broker + cache + rate-limit |
| `mailpit` | `axllent/mailpit:latest` | SMTP capture in dev |

PostgreSQL extensions `unaccent` and `pg_trgm` are created via `docker/initdb/01-extensions.sql` on first start.

## Required env (.env)

| Name | Default | Notes |
|---|---|---|
| `SECRET_KEY` | placeholder | rotate per env |
| `DEBUG` | `0` | `1` only in dev |
| `ALLOWED_HOSTS` | `*` | space-separated in prod |
| `DATABASE_URL` | `postgres://nf:nf@db:5432/newsforge` | psycopg URL |
| `REDIS_URL` | `redis://redis:6379/0` | cache + rate-limit |
| `CELERY_BROKER_URL` | `redis://redis:6379/1` | |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/2` | |
| `USER_AGENT` | `newsforge/0.1` | sent on outbound fetches |
| `HTTP_TIMEOUT` | `20` | seconds per fetch |
| `MAX_RESPONSE_BYTES` | `5242880` | 5 MB cap |
| `PER_DOMAIN_MIN_INTERVAL` | `30` | seconds between fetches per domain |
| `SMTP_HOST` / `SMTP_PORT` | `mailpit` / `1025` | dev defaults |
| `DEFAULT_FROM_EMAIL` | `no-reply@newsforge.local` | |
| `JWT_SIGNING_KEY` | placeholder | required in prod |
| `LOG_LEVEL` | `INFO` | |
| `LOG_FORMAT` | `json` | |

## First-run

```bash
cp .env.example .env
docker compose up -d db redis
docker compose run --rm api migrate
docker compose up -d api worker beat mailpit
```

OpenAPI:
- Schema: `GET /api/schema/`
- Swagger UI: `GET /api/schema/swagger-ui/`

## Scale-out checklist

1. Drop `pgbouncer` in front of Postgres once you exceed ~5 app nodes.
2. Move FTS to a read replica when search QPS dominates write throughput.
3. Partition `articles_article` by `published_at` monthly past 50M rows.
4. Bump `CELERY_CONCURRENCY` per worker only after watching the per-feed RL — fetch throughput is bottlenecked there, not on CPU.
