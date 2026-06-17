# ADR-0006 — Celery `acks_late=True` + `worker_prefetch_multiplier=1`

**Status:** accepted

## Context

`fetch_feed` is the dominant task: a robots.txt check (5 s timeout, on a cache miss) plus the
feed request (`HTTP_TIMEOUT`, 20 s) plus parsing. With
the Celery defaults (`prefetch_multiplier=4`, `acks_late=False`) each worker process grabs
four messages at once, so one slow fetch holds up three other tasks while other processes
sit idle, and a crash loses messages that were already acknowledged.

## Decision

- `worker_prefetch_multiplier=1` — one reserved message per worker process.
- `task_acks_late=True` — acknowledge after the task finishes; a crashed worker's message is
  redelivered.
- `task_soft_time_limit=60`, `task_time_limit=90` (`CELERY_TASK_SOFT_TIME_LIMIT`,
  `CELERY_TASK_TIME_LIMIT`) — a stuck task cannot hold a worker process forever. The batched
  `cleanup_old_articles` sets its own 300 / 360 s.
- The Redis transport's default visibility timeout (1 hour) is kept; it is far above every
  hard time limit.

## Trade-offs

- More broker round-trips. Negligible next to network-bound tasks.
- Redelivered tasks must be idempotent: the article upsert dedups on guid and content hash,
  an article is handed to tagging and fan-out once (`processed_at` is claimed atomically),
  tag assignment uses `get_or_create`, and delivery skips pairs already logged as successful
  and leases the pair while it is being sent (ADR-0005).

## Consequences

Tasks are routed explicitly by module to two queues: `default` for the ingestion pipeline
(fetch, articles, tags, instant delivery) and the per-minute `enqueue_due_feeds` tick, `low`
for daily and maintenance work (digest, robots cache, cleanup). This keeps a long cleanup or
digest run from delaying the pipeline only when the queues are served by separate workers:
the compose worker consumes both (`CELERY_QUEUES=default,low`) in one pool, which is enough
for a small install. Slow fetches and fast article tasks still share `default`; with
prefetch 1 a slow fetch blocks only its own process. Run a second worker with
`CELERY_QUEUES=low` (and the first with `default`) when maintenance starts to compete with
ingestion.
