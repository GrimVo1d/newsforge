# THREAT_MODEL — newsforge

STRIDE applied to the FTS-crawler / subscription service.

## Assets

1. **User accounts** (JWT-protected). Read access to public articles is anonymous.
2. **User-owned subscriptions** — contain webhook URLs and the **plaintext webhook secret** (returned exactly once).
3. **Outbound HTTP capability** of the worker — high-value to an attacker.
4. **`articles_article` corpus** — public, low secrecy, but integrity matters (tampering ⇒ ranking distortion).

## STRIDE

### Spoofing
- **JWT replay** — short access TTL (15 min) + refresh rotation.
- **Webhook receiver spoofing** — we sign payloads with HMAC-SHA256; receivers verify against the secret they hold.

### Tampering
- **HTML injection from feeds** — every body/summary passes through `bleach` whitelist (`apps.articles.normalizer.sanitize_html`).
- **Search query injection** — we whitelist regconfig (`coerce_lang`), use parameterized SQL everywhere, never string-format user input.

### Repudiation
- All deliveries are recorded in `subscriptions_deliverylog` with `(subscription_id, article_id)` unique. Receivers can be told which articles were sent and when.

### Information disclosure
- Webhook secret is stored as `passlib.argon2` hash; plaintext is returned in the API response once and never persisted in cleartext.
- Owner-scoped queryset on `SubscriptionViewSet` prevents IDOR.

### Denial of service
- **Crawler DoS against feeds** — per-domain rate limit, robots.txt cache, polite UA, ETag/IMS.
- **Self-DoS via search** — `LIMIT` capped at 100; large `OFFSET` should be replaced with keyset on hot paths.
- **Webhook backpressure** — retries with exponential backoff and `max_retries=5` ceiling; `delivery_log` unique constraint prevents duplicate-storm.

### Elevation of privilege
- **SSRF** — `assert_public_url` rejects private/loopback/link-local/multicast/reserved addresses at the boundary AND inside the fetcher (mitigates TOCTOU). See ADR-0003.
- **Tag-rule abuse** — TagRules are owner-scoped via the `owner_id` FK.

## Out of scope

- DDOS at the edge (assume a CDN / reverse proxy in front).
- Compromise of the worker host (assume container isolation).
- Long-tail cryptographic attacks on argon2 (`passlib` defaults are fine).

## Non-mitigated

- Receiver-side abuse: if a receiver leaks the webhook secret, an attacker can spoof us. We can rotate the secret via `PATCH /subscriptions/{id}/`.
- Multi-feed correlation attacks (same content across many feeds) — by design we dedupe, so an attacker cannot inflate counts.
