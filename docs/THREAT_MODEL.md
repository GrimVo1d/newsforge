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
  throttle per client address (an IPv6 client per `/64`), and registration also has a daily
  cap (20 accounts per address); `X-Forwarded-For` is ignored unless `NUM_PROXIES` says how
  many trusted proxies set it, so a client cannot pick a fresh bucket per request. Django
  password validators reject weak passwords.
- **Forged webhooks** — every delivery is signed with HMAC-SHA256 over timestamp and body
  using a per-subscription secret; receivers verify the signature and the timestamp window.
  A subscription without a secret (only possible by editing the database) is not sent.

### Tampering

- **HTML from feeds** — summary and body pass a `bleach` whitelist (no scripts, styles or
  event handlers; links and images limited to `http`, `https`, `mailto`); titles and authors
  are stored as plain text; entries whose link is not `http(s)` are dropped.
- **SQL injection** — every query is parameterized; text-search configuration names come from
  a whitelist; search parameters are validated (types, ranges, lengths).
- **Search snippets** — `highlight` is built from tag-stripped text and HTML-escaped as a
  whole before the `<b>` marks are added, so its only markup is `<b>`; no remote images,
  links or scripts from feed text end up in it.
- **Shared data** — only staff can write feeds, tags and tag rules.
- **Email header injection** — subjects are collapsed to one line; addresses are validated.

### Repudiation

- Every delivery attempt is recorded in `subscriptions_deliverylog` (time, attempts, status,
  error) and visible to the subscription owner.

### Information disclosure

- Subscriptions are filtered by owner in the queryset; other users get `404`, not `403`.
- Unhandled errors answer `{"code": "server_error"}` without a traceback or message.
- The webhook secret is returned only when issued (create, switch to webhook, rotate).
- Crawl state of feeds (errors, statuses, schedule) is visible to staff only.
- `/metrics` answers `404` unless a bearer token matches `METRICS_TOKEN`.
- A feed or webhook host that is private or does not resolve gets one generic message; the
  resolved address (or the failed lookup) is only logged, so the API cannot be used to map
  internal DNS. Other rejections (scheme, port, credentials in the URL) name the rule that
  was broken, which says nothing about the network.
- Articles of deleted feeds disappear from search, listings and subscription matching.
- Production settings are the default of the image and of every server entry point (gunicorn,
  celery); only `manage.py` and compose pick dev. They have no default `SECRET_KEY`,
  `ALLOWED_HOSTS`, database, Redis or broker URL (a weak key, or one ever committed to this
  repository, refuses to start), `DEBUG=False`, HTTPS redirect, HSTS, secure cookies and a
  JSON-only API; compose binds every port to localhost.

### Denial of service

- **Against feed servers** — robots.txt, per-domain rate limit, conditional requests,
  backoff, pausing of failing feeds, a minimum polling interval of 5 minutes.
- **Against the worker** — per-request deadline and body cap (5 MB for feeds, 500 KB for
  robots.txt) applied to the decompressed and the raw size, so gzip bombs and endless
  trailers stop at the cap; webhook answers are not read beyond the status line and headers;
  at most 200 entries per fetch, Celery soft / hard time limits.
- **Against the API** — global anonymous and per-user throttles, a separate search throttle,
  `limit` ≤ 100 and `offset` ≤ 10000 on every list, `q` ≤ 256 characters, `ts_headline` only
  on the result page.
- **Webhook backpressure** — bounded retries with backoff; already delivered pairs are
  skipped.
- **Subscription abuse** — at most `MAX_SUBSCRIPTIONS_PER_USER` (20) subscriptions per user,
  checked under a lock on the user, which bounds the matching work per article and the mail /
  webhook volume per account; one email address or webhook URL can be the target of at most
  `MAX_ACCOUNTS_PER_TARGET` (5) accounts, counted on a normalized key (email case, `+tags`,
  Gmail dots, IDN domains; quoted local parts and address literals are refused; webhook host
  case, query, fragment, and the path as servers resolve it: dot segments, repeated slashes,
  percent-encoding, `;params`, case, trailing slash) under a transaction lock on that key,
  and new accounts per address are capped per day, so many accounts cannot be pointed at one
  victim.
- **Delivery log disclosure** — the log a user reads stores a failure category, never the
  text of an SMTP or HTTP error, so it does not reveal mail server internals; details go to
  the worker log.

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
- **No email confirmation.** A user can subscribe any address or webhook URL. Mails and
  webhooks go there only for queries the user chose, at most once per matching article and
  subscription, and identify the service. The per-target cap counts webhook endpoints (host and path), not
  hosts (shared webhook services such as chat integrations put every customer on one host),
  so one host can still receive several URLs' worth of deliveries.
- **Plaintext webhook secrets in the database.** Needed for HMAC; database access already
  means full control.
- **Redis without a password** in the compose stack. It is not published beyond localhost;
  production should use an authenticated, private Redis.
- **Public OpenAPI schema.** It describes no secrets; hiding it would be obscurity. The
  Swagger UI page loads its scripts from the jsDelivr CDN (drf-spectacular's default); the
  API itself does not depend on it. Self-host them (`SWAGGER_UI_DIST`) or drop the route if
  that matters.
- **Public feed URLs.** Anonymous users see each feed's `url`. Staff must not add feeds whose
  URL carries a token or other credentials.
- **Articles of paused feeds stay visible.** An inactive (not deleted) feed is hidden from the
  public feed list, but its already fetched articles remain in listings and search.
- **Response headers are not covered by the deadline.** httpx timeouts apply per read, so a
  server that trickles headers is bounded by the Celery hard time limit (90 s) instead.

## Out of scope

- Volumetric DDoS (expected to be handled by a CDN or reverse proxy).
- Compromise of the host or the container runtime.
