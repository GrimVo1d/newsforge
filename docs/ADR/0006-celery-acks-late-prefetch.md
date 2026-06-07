# ADR-0006 — Celery `acks_late=True` + `worker_prefetch_multiplier=1`

**Status:** accepted

## Context

`fetch_feed` is the dominant task and can take up to `HTTP_TIMEOUT` (20 s) plus parsing. With
the Celery defaults (`prefetch_multiplier=4`, `acks_late=False`) each worker process grabs
four messages at once, so one slow fetch holds up three other tasks while other processes
sit idle, and a crash loses messages that were already acknowledged.

## Decision

- `worker_prefetch_multiplier=1` — one reserved message per worker process.
- `task_acks_late=True` — acknowledge after the task finishes; a crashed worker's message is
  redelivered.
- `task_soft_time_limit=60`, `task_time_limit=90` (`CELERY_TASK_SOFT_TIME_LIMIT`,
  `CELERY_TASK_TIME_LIMIT`) — a stuck task cannot hold a worker process forever.
- The Redis transport's default visibility timeout (1 hour) is kept; it is far above the
  hard time limit.

## Trade-offs

- More broker round-trips. Negligible next to network-bound tasks.
- Redelivered tasks must be idempotent: the article upsert is (`ON CONFLICT DO NOTHING`),
  tag assignment uses `get_or_create`, and delivery skips pairs already logged as successful.

## Consequences

Slow and fast work are separated by queue (`default` and `low`) and routed explicitly by task
module.
