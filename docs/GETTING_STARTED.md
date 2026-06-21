# Getting started

This guide runs the full stack locally, adds a feed, searches it and sets up a subscription.
Everything runs in Docker; nothing is installed on the host apart from Docker itself.

## 1. Start the stack

```bash
cp .env.example .env    # optional, see "Configuration" below
make up
make ps                 # api should become "healthy" within a few seconds
```

`make up` builds the image and starts:

| Service | What it does | Host port |
|---|---|---|
| `db` | PostgreSQL 16 | `127.0.0.1:5432` |
| `redis` | Celery broker, cache, rate limits | `127.0.0.1:6379` |
| `mailpit` | SMTP sink with a web UI for subscription emails | `127.0.0.1:8025` |
| `migrate` | applies migrations once, then exits | — |
| `api` | gunicorn + Django | `127.0.0.1:8000` |
| `worker` | Celery worker (`default` and `low` queues) | — |
| `beat` | Celery Beat: polls due feeds every minute | — |

The compose stack uses `newsforge.settings.dev` (`DEBUG=True`). Ports are bound to
localhost only.

## 2. Accounts

Feeds, tags and tag rules are shared by all users, so only staff may change them. Create a
staff account:

```bash
make superuser
```

Any user can register through the API and manage their own subscriptions. Passwords go
through Django's standard validators (length, similarity, common and numeric passwords).

```bash
API=http://localhost:8000/api/v1

curl -s -X POST $API/auth/register/ -H 'Content-Type: application/json' \
  -d '{"username": "reader", "password": "a-long-passphrase"}'
# {"id": 2, "username": "reader"}

curl -s -X POST $API/auth/token/ -H 'Content-Type: application/json' \
  -d '{"username": "reader", "password": "a-long-passphrase"}'
# {"refresh": "...", "access": "..."}
```

Access tokens live 15 minutes, refresh tokens 7 days; renew with
`POST /auth/token/refresh/ {"refresh": "..."}`. The auth endpoints are throttled
(`THROTTLE_AUTH`, 10 requests per minute by default).

In the examples below `$STAFF` and `$TOKEN` hold the access tokens of the staff account and
of a regular user. Hosts under `example.internal` are placeholders: they do not resolve, so
feed and webhook URLs built on them are rejected with `400` (`ssrf_blocked`). Put a real
public feed or receiver in their place.

## 3. Add a feed (staff)

```bash
curl -s -X POST $API/feeds/ -H "Authorization: Bearer $STAFF" \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://blog.example.internal/rss.xml", "interval_seconds": 1800}'
```

- The URL must be `https://` on the default port and resolve to public addresses only;
  otherwise the request fails with `400`. Plain `http://` is accepted only with
  `ALLOW_PLAIN_HTTP=true`.
- The URL is stored in one canonical spelling: lowercase scheme and host (an internationalized
  host in its `xn--` form), no default port, no `#fragment`. Another spelling of an existing
  feed's URL is rejected as a duplicate.
- `interval_seconds` is the polling interval, at least 300 (default 1800).
- A new feed is due immediately; Beat picks it up within a minute. To fetch an existing feed
  right away: `POST $API/feeds/{id}/refresh/`.
- Each article's language is detected from its text; a feed's `language` is used for articles
  too short or ambiguous for detection.

Staff see the crawl state of every feed (`last_status`, `consecutive_errors`,
`next_fetch_at`, `disabled_until`); everyone else sees active feeds without it.

`last_status` is one of `ok`, `not_modified`, `http_error`, `network_error`, `parse_error`,
`too_large`, `ssrf_blocked`, `robots_blocked`. After an error the next attempt is delayed
exponentially; after 6 consecutive errors the feed is paused for 24 hours (`refresh` ends
the pause). Changing a feed's `url` resets its crawl state; adding the URL of a deleted feed
again restores that feed with its articles.

## 4. Read and search

```bash
curl -s "$API/articles/?feed=1"                          # newest first
curl -s "$API/articles/?tag=django&published_after=2026-05-01T00:00:00Z"
curl -s "$API/articles/?language=ru"                     # russian / ru, english / en, simple
curl -s "$API/articles/42/"                              # includes the sanitized body
curl -s "$API/search/?q=django+release&lang=en"
curl -s "$API/search/?q=%22async+views%22+-celery&sort=date&feed=1,2"
```

`q` uses web-search syntax: quoted phrases, `or`, `-word` to exclude. See
[SEARCH.md](SEARCH.md) for all parameters, ranking and the typo-tolerant fallback.

## 5. Tags and tag rules (staff)

```bash
curl -s -X POST $API/tags/ -H "Authorization: Bearer $STAFF" \
  -H 'Content-Type: application/json' -d '{"name": "Django", "slug": "django"}'

# tag every new article that mentions any of these words
curl -s -X POST $API/tag-rules/ -H "Authorization: Bearer $STAFF" \
  -H 'Content-Type: application/json' \
  -d '{"name": "django", "tag": 1, "keywords": ["django", "drf"], "match": "any"}'

# tag an article by hand
curl -s -X POST $API/articles/42/tags/ -H "Authorization: Bearer $STAFF" \
  -H 'Content-Type: application/json' -d '{"tag_id": 1}'
```

Rules run on new articles only (case-insensitive substring match against the text of title,
summary and body, without markup; `match` is `any` or `all`; an optional `language` limits a
rule to one language). Tagging an article by hand answers `201`, or `200` if it already had
the tag.

## 6. Subscriptions

A subscription is a saved query plus optional `feeds` and `tag_ids` filters. `interval` is
`instant` (checked for every new article) or `daily` (checked at 09:00 UTC against the
articles added since the previous run, at most 100). Either way each matched article is a
separate delivery: one email or one webhook call per article, there is no combined digest. Each user can keep up to 20 subscriptions
(`MAX_SUBSCRIPTIONS_PER_USER`), and one email address or webhook URL can be used by at most 5
accounts (`MAX_ACCOUNTS_PER_TARGET`). Spelling variants count as one target: email case,
`+tags` and Gmail dots, webhook host case, query, fragment and a trailing slash. The `feeds` and `tag_ids` filters must name
existing feeds and tags; a `PUT` without them clears them, a `PATCH` keeps them.

### Email

```bash
curl -s -X POST $API/subscriptions/ -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name": "django", "q": "django", "delivery": "email", "email_to": "me@example.internal"}'
```

In the dev stack every email lands in Mailpit at <http://localhost:8025/>.

### Webhook

```bash
curl -s -X POST $API/subscriptions/ -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name": "releases", "q": "release", "tag_ids": [1],
       "delivery": "webhook", "webhook_url": "https://hooks.example.internal/newsforge"}'
```

The response contains `webhook_secret`. **It is shown only once**; store it on the receiver.
If it is lost or leaked, issue a new one with `POST $API/subscriptions/{id}/rotate-secret/`.

Each delivery is a `POST` with a JSON body:

```json
{"id": 42, "title": "Django 5.2 released", "url": "https://...", "summary": "...",
 "feed_id": 1, "published_at": "2026-05-04T12:00:00+00:00"}
```

and these headers:

| Header | Value |
|---|---|
| `X-NF-Timestamp` | Unix time of the attempt |
| `X-NF-Signature` | `sha256=` + hex HMAC-SHA256 of `"<timestamp>." + raw body`, keyed with the secret |
| `X-Idempotency-Key` | stable per (subscription, article); the same on every retry |

A receiver should verify the signature against the raw body, reject old timestamps and
ignore idempotency keys it has already processed:

```python
import hashlib
import hmac
import time


def verify(secret: str, body: bytes, timestamp: str, signature: str, tolerance: int = 300) -> bool:
    if abs(time.time() - int(timestamp)) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return hmac.compare_digest(f"sha256={expected.hexdigest()}", signature)
```

Delivery rules:

- A `2xx` answer counts as delivered. Redirects are not followed; a `3xx` is a failed delivery.
- `5xx`, `408`, `429`, timeouts and connection errors are retried with exponential backoff,
  up to 5 retries. Other `4xx` answers are final. The answer's body is not read.
- Every attempt is recorded; see them with `GET $API/subscriptions/{id}/deliveries/`
  (`succeeded`, `attempts`, `http_status`, `error`), newest pair first. `error` is a short
  category (`receiver answered 503`, `timeout`, `connection failed`, `mail server
  unavailable`, `blocked: …`); the receiver's or mail server's own text is not stored. For email,
  `http_status` holds the SMTP reply code: `250` when the server accepted the message, the
  refusal code (e.g. `550`) when it refused the recipient for good.
- The webhook URL is re-checked on every attempt; a URL that now resolves to a private
  address is recorded as `blocked` and not retried.

## 7. Tests and checks

```bash
make test        # pytest against the compose PostgreSQL and Redis
make cov         # with a coverage report (the build fails below 85%)
make lint        # ruff
make typecheck   # mypy --strict
make pre-commit  # all pre-commit hooks
```

To run hooks on every `git commit`, install pre-commit in a project virtualenv and run
`pre-commit install`; the mypy hook expects the dev dependencies (`pip install -e ".[dev]"`)
in that environment.

## Configuration

All settings come from environment variables. `.env.example` lists the ones worth changing
locally, with their defaults; compose reads `.env` automatically. The database, Redis and
broker URLs are fixed in `docker-compose.yml` to the stack's own services, so `.env` cannot
point them elsewhere. [DEPLOYMENT.md](DEPLOYMENT.md) has the full reference and
the production settings.

## Troubleshooting

| Symptom | Check |
|---|---|
| `make up` hangs on `api` | `make logs`; `migrate` must exit 0 first (`docker compose logs migrate`) |
| feed stays without `last_fetched_at` | `docker compose logs worker beat`; is the feed `is_active` and not `disabled_until`? |
| `last_status: robots_blocked` | the site's robots.txt disallows the feed path for the product token of `USER_AGENT` (`newsforge`), or robots.txt answered `5xx` (rechecked after 30 minutes) |
| `last_status: ssrf_blocked` | the host resolves to a private address or does not resolve, or a redirect leads to such a host or to `http://`; the worker log has the details |
| no emails in Mailpit | `GET /subscriptions/{id}/deliveries/`; does the query match the article's language? |
| `429` responses | throttling; tune `THROTTLE_*` |
