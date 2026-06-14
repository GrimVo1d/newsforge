# ADR-0005 — At-least-once webhook delivery with receiver-side idempotency

**Status:** accepted (revised: signatures used the stored argon2 hash as the key, which
receivers could not reproduce, and failed attempts were not recorded; later, overlapping
attempts could both send and a late failure could overwrite a success)

## Context

Subscriptions deliver to user-controlled webhooks and mailboxes. Networks drop responses,
receivers go down, and workers can crash mid-task (`acks_late=True` redelivers the message).

## Decision

- **At-least-once.** `deliver` retries on network errors, deadlines, SMTP / socket errors and
  on `5xx`, `408` and `429` answers, with exponential backoff and jitter, up to 5 retries.
  Other answers are final: `2xx` is a success; `3xx` (redirects are not followed) and other
  `4xx` are failures. For email, a recipient or message refused with a `5xx` SMTP code is
  final; temporary `4xx` codes and our own errors (authentication, sender) are retried. The
  webhook body is not read: a `2xx` with a broken body still counts as delivered.
- **One log row per (subscription, article).** `subscriptions_deliverylog` has
  `UNIQUE (subscription_id, article_id)`; every attempt updates the row (`attempts`,
  `succeeded`, `http_status` — the SMTP code for email —, `error`, `delivered_at`).
- **A lease per pair.** Before sending, `deliver` locks the row and sets `leased_until`
  (2 minutes, longer than one attempt). A pair that already succeeded is skipped; a pair
  whose lease is held by another task is retried later (`DeliveryInFlightError`), so a
  redelivered task or an overlapping digest does not send twice from our side. Recording
  the attempt releases the lease; a lease left by a crashed worker expires.
- **No downgrade.** Once `succeeded` is true, later attempts no longer change the row.
- **Gone is not an error.** A subscription paused or deleted, or an article (or its feed)
  deleted while the task waited, ends the task without a send, a log row or a retry.
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
