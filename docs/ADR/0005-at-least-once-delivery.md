# ADR-0005 — At-least-once webhook delivery with receiver-side idempotency

**Status:** accepted

## Context

Subscriptions deliver to user-controlled webhooks. The network can drop responses; workers can crash; we use `acks_late=True` and retries.

## Decision

- **At-least-once** delivery: retries with `autoretry_for=(HTTPError,)`, exponential backoff, jitter, max 5 attempts.
- **Per-attempt idempotency key**: `X-Idempotency-Key = sha256(subscription_id || article_id)` — deterministic, allows the receiver to dedupe by storing seen keys.
- **Internal dedup**: `subscriptions_deliverylog` has `UNIQUE (subscription_id, article_id)`. On a successful delivery we insert a row inside the worker; on a duplicate insert (after a re-delivery) we catch `IntegrityError` and return `{"deduped": True}` — the work was already done.

## Why not exactly-once

Exactly-once over network requires two-phase commit between us and the receiver. Receivers we cannot control will not implement it. We pick a simpler, well-understood contract.

## Consequences

- Receivers can implement a 1-line check: `if X-Idempotency-Key in seen: return 200`.
- The `delivery_log` is the source of truth for which deliveries have been recorded — clients can poll `GET /subscriptions/{id}/deliveries/` if needed (future endpoint).
