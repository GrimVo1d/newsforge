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
  throttle per client address; `X-Forwarded-For` is ignored unless `NUM_PROXIES` says how many
  trusted proxies set it, so a client cannot pick a fresh bucket per request. Django password
  validators reject weak passwords.
- **Forged webhooks** — every delivery is signed with HMAC-SHA256 over timestamp and body
  using a per-subscription secret; receivers verify the signature and the timestamp window.

### Tampering

- **HTML from feeds** — summary and body pass a `bleach` whitelist (no scripts, styles or
  event handlers; links and images limited to `http`, `https`, `mailto`); titles and authors
  are stored as plain text; entries whose link is not `http(s)` are dropped.
- **SQL injection** — every query is parameterized; text-search configuration names come from
  a whitelist; search parameters are validated (types, ranges, lengths).
- **Search snippets** — `highlight` is built from tag-stripped text, so its only markup is
  `<b>`; no remote images or links from feed HTML end up in it.
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
- Rejected feed and webhook URLs get one generic message; the resolved private address (or a
  failed lookup) is only logged, so the API cannot be used to map internal DNS.
- Articles of deleted feeds disappear from search, listings and subscription matching.
- Production settings: no default `SECRET_KEY` or `ALLOWED_HOSTS` (and a short or placeholder
  key refuses to start), `DEBUG=False`, HTTPS redirect, HSTS, secure cookies; compose binds
  every port to localhost.

### Denial of service

- **Against feed servers** — robots.txt, per-domain rate limit, conditional requests,
  backoff, pausing of failing feeds, a minimum polling interval of 5 minutes.
- **Against the worker** — per-request deadline and body cap (5 MB for feeds, 200 KB for
  robots.txt, 64 KB for webhook answers) applied to the decompressed size, so gzip bombs stop
  at the cap; at most 200 entries per fetch, Celery soft / hard time limits.
- **Against the API** — global anonymous and per-user throttles, a separate search throttle,
  `limit` ≤ 100, `offset` ≤ 10000, `q` ≤ 256 characters, `ts_headline` only on the result page.
- **Webhook backpressure** — bounded retries with backoff; already delivered pairs are
  skipped.
- **Subscription abuse** — at most `MAX_SUBSCRIPTIONS_PER_USER` (20) subscriptions per user,
  which bounds the matching work per article and the mail / webhook volume per account.

### Elevation of privilege

- **SSRF** — `apps.core.safe_http` pins connections to checked public addresses (IPv6 forms
  that embed an IPv4 address, such as NAT64, are checked by that address), re-checks every
  redirect, refuses non-default ports and plain `http` by default. See ADR-0003.
- **Privilege boundaries** — staff rights come only from Django's `is_staff`; there is no
  self-service path to it.

## Accepted risks

- **No token revocation.** Logging out does not invalidate tokens; a stolen refresh token
  works until it expires (7 days). A token blacklist would need extra storage.
- **Username enumeration.** Registration answers `409 username_taken`; the auth throttle
  limits how fast this can be probed.
- **No email confirmation, no per-target delivery limit.** A user can subscribe any address
  or webhook URL. Mails and webhooks go there only for queries the user chose, at most once per
  matching article and subscription, and identify the service; the subscription cap bounds the
  volume per account, but many accounts can still point at one target.
- **Plaintext webhook secrets in the database.** Needed for HMAC; database access already
  means full control.
- **Redis without a password** in the compose stack. It is not published beyond localhost;
  production should use an authenticated, private Redis.
- **Public OpenAPI schema.** It describes no secrets; hiding it would be obscurity.
- **Public feed URLs.** Anonymous users see each feed's `url`. Staff must not add feeds whose
  URL carries a token or other credentials.
- **Articles of paused feeds stay visible.** An inactive (not deleted) feed is hidden from the
  public feed list, but its already fetched articles remain in listings and search.
- **Response headers are not covered by the deadline.** httpx timeouts apply per read, so a
  server that trickles headers is bounded by the Celery hard time limit (90 s) instead.

## Out of scope

- Volumetric DDoS (expected to be handled by a CDN or reverse proxy).
- Compromise of the host or the container runtime.
