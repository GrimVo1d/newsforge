# ADR-0005 — At-least-once webhook delivery with receiver-side idempotency

**Status:** accepted (revised: signatures used the stored argon2 hash as the key, which
receivers could not reproduce, and failed attempts were not recorded)

## Context

Subscriptions deliver to user-controlled webhooks and mailboxes. Networks drop responses,
receivers go down, and workers can crash mid-task (`acks_late=True` redelivers the message).

## Decision

- **At-least-once.** `deliver` retries on network errors, deadlines, SMTP / socket errors and
  on `5xx`, `408` and `429` answers, with exponential backoff and jitter, up to 5 retries.
  Other answers are final: `2xx` is a success; `3xx` (redirects are not followed) and other
  `4xx` are failures.
- **One log row per (subscription, article).** `subscriptions_deliverylog` has
  `UNIQUE (subscription_id, article_id)`; every attempt updates the row (`attempts`,
  `succeeded`, `http_status`, `error`). A pair that already succeeded is skipped, so a
  redelivered task or an overlapping digest does not send twice from our side.
- **Idempotency key.** `X-Idempotency-Key = sha256("<subscription_id>:<article_id>")` is the
  same on every retry; receivers drop keys they have seen.
- **Signature.** A random secret per webhook subscription is stored in plaintext (HMAC needs
  it), returned once when issued and never serialized again; `POST .../rotate-secret/` issues
  a new one. Each request carries `X-NF-Timestamp` and
  `X-NF-Signature: sha256=<hex HMAC-SHA256(secret, "<timestamp>." + body)>`, so receivers can
  check both authenticity and freshness.

## Why not exactly-once

That needs a two-phase protocol with the receiver, which receivers we do not control will not
implement. At-least-once plus an idempotency key is simple and well understood.

## Consequences

- A receiver may see the same payload more than once and must deduplicate by key.
- Receivers should reject timestamps outside a small window (5 minutes) to stop replays.
- Anyone with database read access can read webhook secrets; database access is already
  equivalent to full control of the service.
- The delivery log is visible to the owner at `GET /subscriptions/{id}/deliveries/`.
