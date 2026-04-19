# ADR-0006 — Celery `acks_late=True` + `worker_prefetch_multiplier=1`

**Status:** accepted

## Context

`fetch_feed` is the dominant task and can run 5–30 seconds (network + parse). The default Celery configuration (`prefetch_multiplier=4`, `acks_late=False`) means each worker eagerly grabs 4 messages from the broker — a single 30s fetch blocks 3 other tasks in its queue even while other workers are idle.

## Decision

- `worker_prefetch_multiplier=1` — one message per worker at a time. Slow fetches no longer hold up fast ones.
- `task_acks_late=True` — ack after task completion. Worker crashes cause the broker to redeliver; combined with naturally-idempotent DB ops (`INSERT ... ON CONFLICT`), retries are safe.
- Visibility timeout 600s — accommodates worst-case fetch + parse.

## Trade-offs

- More broker round-trips (each worker fetches one at a time). Negligible vs. the wall-clock savings.
- Redelivered messages must be idempotent. The upsert path is. Webhook delivery is via `delivery_log` uniqueness.

## Consequences

`prefetch=1` interacts with priority queues — we kept `default` and `low` separate and route tasks explicitly.
