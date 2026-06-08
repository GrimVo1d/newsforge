# Deployment

## Image

`docker/Dockerfile` is a multi-stage build on `python:3.12-slim`:

| Stage | Contents |
|---|---|
| `builder` | virtualenv in `/opt/venv` with the runtime dependencies |
| `runtime` | the virtualenv, `manage.py` and `src/`; runs as the unprivileged user `app` (uid 10001) |
| `dev` | builder + dev dependencies and git, source mounted at `/app`; used by `make test` / `lint` / `typecheck` |

`docker/entrypoint.sh` selects the process by its first argument:

| Command | Runs |
|---|---|
| `api` (default) | `gunicorn newsforge.wsgi:application` on `0.0.0.0:8000`, `GUNICORN_WORKERS` workers (4) |
| `worker` | `celery -A newsforge worker`, queues `CELERY_QUEUES` (`default,low`), `CELERY_CONCURRENCY` (4) |
| `beat` | `celery -A newsforge beat` with its schedule file in `/tmp` |
| `migrate` | `python manage.py migrate --noinput` |
| anything else | executed as is, e.g. `python manage.py createsuperuser` |

## Compose stack

| Service | Image | Notes |
|---|---|---|
| `db` | `postgres:16-alpine` | volume `db_data`; the `unaccent` and `pg_trgm` extensions are created by a migration |
| `redis` | `redis:7-alpine` | broker (db 1), results (db 2), cache and rate limits (db 0); no persistence |
| `mailpit` | `axllent/mailpit:v1.31.6` | SMTP sink for development |
| `migrate` | local build | runs once; `api`, `worker` and `beat` wait for it to succeed |
| `api` | local build | health check on `/health/live` |
| `worker`, `beat` | local build | |
| `dev` | local build, `dev` target | profile `dev`; test settings |

All published ports are bound to `127.0.0.1`. The compose file targets local development:
it uses `newsforge.settings.dev`, fixed database credentials and Redis without a password.

## Configuration

Settings are read from the environment (`django-environ`); compose also loads `.env`.

### Django

| Variable | Default | Notes |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | `newsforge.settings.dev` | `newsforge.settings.prod` in production |
| `SECRET_KEY` | dev-only placeholder | **required** in prod; random, at least 50 characters (prod refuses to start otherwise) |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` (`*` in dev) | **required** in prod; comma-separated |
| `CSRF_TRUSTED_ORIGINS` | empty | comma-separated origins |
| `DEBUG` | `False` (`True` in dev) | |
| `DATABASE_URL` | `postgres://nf:nf@db:5432/newsforge` | |
| `REDIS_URL` | `redis://redis:6379/0` | cache, rate limits, robots.txt cache, readiness |
| `CELERY_BROKER_URL` | `redis://redis:6379/1` | |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/2` | |
| `LOG_LEVEL` | `INFO` | logs go to stdout |
| `METRICS_TOKEN` | empty | `/metrics` is disabled (404) while empty |

### API throttling

| Variable | Default |
|---|---|
| `THROTTLE_ANON` | `120/min` |
| `THROTTLE_USER` | `600/min` |
| `THROTTLE_AUTH` | `10/min` (register, token, refresh) |
| `THROTTLE_SEARCH` | `60/min` |
| `NUM_PROXIES` | `0` |

Throttle counters live in the Redis cache, keyed by user for authenticated requests and by
client address otherwise (registration and token requests are always anonymous). With
`NUM_PROXIES=0` the address is `REMOTE_ADDR` and `X-Forwarded-For` is ignored, since clients
can set it to anything. Behind reverse proxies set `NUM_PROXIES` to their number: the address
is then taken from `X-Forwarded-For`, as appended by the outermost trusted proxy. Without it,
all clients behind the proxy share one bucket.

### Subscriptions

| Variable | Default | Notes |
|---|---|---|
| `MAX_SUBSCRIPTIONS_PER_USER` | `20` | creating one more answers `400` |

### Crawler

| Variable | Default | Notes |
|---|---|---|
| `USER_AGENT` | `newsforge/0.1` | sent with every outbound request |
| `HTTP_TIMEOUT` | `20` | seconds per feed fetch, all redirects included |
| `MAX_RESPONSE_BYTES` | `5242880` | feed body cap |
| `MAX_ENTRIES_PER_FETCH` | `200` | entries taken from one fetch |
| `PER_DOMAIN_MIN_INTERVAL` | `30` | seconds between fetches from one host |
| `ALLOW_PLAIN_HTTP` | `false` | allow `http://` feed and webhook URLs |

### Email

| Variable | Default |
|---|---|
| `EMAIL_HOST` / `EMAIL_PORT` | `localhost` / `25` (compose: `mailpit` / `1025`) |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | empty |
| `EMAIL_USE_TLS` | `false` |
| `DEFAULT_FROM_EMAIL` | `no-reply@newsforge.local` |

### Processes

| Variable | Default |
|---|---|
| `GUNICORN_WORKERS` | `4` |
| `CELERY_CONCURRENCY` | `4` |
| `CELERY_QUEUES` | `default,low` |
| `CELERY_LOG_LEVEL` | `INFO` |
| `CELERY_TASK_SOFT_TIME_LIMIT` / `CELERY_TASK_TIME_LIMIT` | `60` / `90` seconds |

### Production only (`newsforge.settings.prod`)

| Variable | Default | Notes |
|---|---|---|
| `SECURE_SSL_REDIRECT` | `true` | turn off only if the proxy already redirects |
| `TRUST_X_FORWARDED_PROTO` | `false` | trust `X-Forwarded-Proto: https`; enable only behind a proxy that always sets it |
| `SECURE_HSTS_PRELOAD` | `false` | HSTS itself is on (1 year, subdomains) |

Session and CSRF cookies are marked secure. `python manage.py check --deploy` reports no
security warnings with these settings.

## Production checklist

1. Build the `runtime` target and run `migrate` once per release before starting the new
   `api`, `worker` and `beat` containers.
2. Set `DJANGO_SETTINGS_MODULE=newsforge.settings.prod`, a random `SECRET_KEY`,
   `ALLOWED_HOSTS`, and real `DATABASE_URL`, `REDIS_URL`, broker and SMTP settings.
3. Terminate TLS at a reverse proxy; set `TRUST_X_FORWARDED_PROTO=true` only if it sets the
   header on every request, and `NUM_PROXIES` to the number of proxies in front of the API.
4. Use PostgreSQL 16 with the `unaccent` and `pg_trgm` extensions available (the migration
   creates them, which needs a role allowed to `CREATE EXTENSION`), and a private,
   password-protected Redis.
5. Run exactly one `beat`; scale `worker` and `api` horizontally.
6. Create the first staff account: `docker compose run --rm api python manage.py createsuperuser`.
7. Scrape `/metrics` with `Authorization: Bearer $METRICS_TOKEN`, probe `/health/ready`.

## Scaling notes

1. Put pgbouncer in front of PostgreSQL once there are many app processes.
2. Serve search from a read replica when search load dominates writes.
3. Partition `articles_article` by `published_at` once it grows past tens of millions of rows.
4. Fetch throughput is bounded by the per-domain rate limit, not CPU: more worker
   concurrency helps only with many distinct hosts.
