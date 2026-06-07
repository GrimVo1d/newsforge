# Threat model

STRIDE applied to the crawler, the API and subscription delivery.

## Assets

1. **User accounts** — JWT-protected; passwords hashed with Argon2.
2. **Subscriptions** — queries, webhook URLs, email addresses and webhook secrets of their
   owners.
3. **The worker's outbound HTTP** — the most valuable capability for an attacker (SSRF).
4. **Shared data** — feeds, tags and tag rules; tampering would affect every user.
5. **The article corpus** — public, but its integrity matters for search and notifications.

## Trust boundaries

- Anonymous clients: read feeds (active ones, without crawl state), articles, tags, search.
- Registered users: additionally manage their own subscriptions.
- Staff: manage feeds, tags, tag rules and article tags.
- Feed servers and webhook receivers: untrusted remote parties.

## STRIDE

### Spoofing

- **Stolen access tokens** — access tokens live 15 minutes, refresh tokens 7 days.
- **Brute force** — register / token / refresh endpoints share a 10 requests per minute
  throttle per client; Django password validators reject weak passwords.
- **Forged webhooks** — every delivery is signed with HMAC-SHA256 over timestamp and body
  using a per-subscription secret; receivers verify the signature and the timestamp window.

### Tampering

- **HTML from feeds** — summary and body pass a `bleach` whitelist (no scripts, styles or
  event handlers; links and images limited to `http`, `https`, `mailto`); titles and authors
  are stored as plain text; entries whose link is not `http(s)` are dropped.
- **SQL injection** — every query is parameterized; text-search configuration names come from
  a whitelist; search parameters are validated (types, ranges, lengths).
- **Shared data** — only staff can write feeds, tags and tag rules.
- **Email header injection** — subjects are collapsed to one line; addresses are validated.

### Repudiation

- Every delivery attempt is recorded in `subscriptions_deliverylog` (time, attempts, status,
  error) and visible to the subscription owner.

### Information disclosure

- Subscriptions are filtered by owner in the queryset; other users get `404`, not `403`.
- The webhook secret is returned only when issued (create, switch to webhook, rotate).
- Crawl state of feeds (errors, statuses, schedule) is visible to staff only.
- `/metrics` answers `404` unless a bearer token matches `METRICS_TOKEN`.
- Production settings: no default `SECRET_KEY` or `ALLOWED_HOSTS`, `DEBUG=False`, HTTPS
  redirect, HSTS, secure cookies; compose binds every port to localhost.

### Denial of service

- **Against feed servers** — robots.txt, per-domain rate limit, conditional requests,
  backoff, pausing of failing feeds, a minimum polling interval of 5 minutes.
- **Against the worker** — per-request deadline and body cap (5 MB for feeds, 200 KB for
  robots.txt, 64 KB for webhook answers), at most 200 entries per fetch, Celery soft / hard
  time limits.
- **Against the API** — global anonymous and per-user throttles, a separate search throttle,
  `limit` ≤ 100, `offset` ≤ 10000, `q` ≤ 256 characters, `ts_headline` only on the result page.
- **Webhook backpressure** — bounded retries with backoff; already delivered pairs are
  skipped.

### Elevation of privilege

- **SSRF** — `apps.core.safe_http` pins connections to checked public addresses, re-checks
  every redirect, refuses non-default ports and plain `http` by default. See ADR-0003.
- **Privilege boundaries** — staff rights come only from Django's `is_staff`; there is no
  self-service path to it.

## Accepted risks

- **No token revocation.** Logging out does not invalidate tokens; a stolen refresh token
  works until it expires (7 days). A token blacklist would need extra storage.
- **Username enumeration.** Registration answers `409 username_taken`; the auth throttle
  limits how fast this can be probed.
- **No email confirmation.** A user can subscribe any address. Mails go to that address only
  for queries the user chose, are throttled by matching articles, and identify the service.
- **Plaintext webhook secrets in the database.** Needed for HMAC; database access already
  means full control.
- **Redis without a password** in the compose stack. It is not published beyond localhost;
  production should use an authenticated, private Redis.
- **Public OpenAPI schema.** It describes no secrets; hiding it would be obscurity.

## Out of scope

- Volumetric DDoS (expected to be handled by a CDN or reverse proxy).
- Compromise of the host or the container runtime.
