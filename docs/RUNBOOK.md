# RUNBOOK — newsforge

Operational playbook: 5 alerts + remediation.

## Alert 1 — Feed disabled storm (`disabled_feeds_total` > 5 in 1h)

**Likely cause:** a class of feeds is unreachable (provider outage, our egress blocked, robots policy change).

**Diagnosis:**
```sql
SELECT host(url) AS host, count(*) AS n
FROM feeds_feed
WHERE disabled_until > now() - interval '24h'
GROUP BY 1 ORDER BY 2 DESC LIMIT 20;
```

**Remediation:**
1. If clustered around one host → confirm with `curl -I` from the worker. If DNS / TCP fails, defer until provider recovers.
2. If clustered around `robots_blocked` → check `apps.feeds.robots.invalidate(domain)` and re-fetch `robots.txt`.
3. To force re-enable: `UPDATE feeds_feed SET disabled_until = NULL, consecutive_errors = 0 WHERE id IN (...)` then `POST /api/v1/feeds/{id}/refresh/`.

## Alert 2 — FTS index drift (search returns 0 for content known to be present)

**Likely cause:** trigger disabled / not migrated / stopped firing on legacy rows.

**Diagnosis:**
```sql
SELECT count(*) AS missing
FROM articles_article WHERE tsv IS NULL AND NOT is_deleted;
```

**Remediation:**
```
make reindex-tsv
```
(or directly: `UPDATE articles_article SET title = title;` — fires the BEFORE-UPDATE trigger). Done in batches:
```sql
UPDATE articles_article SET title = title
WHERE id IN (SELECT id FROM articles_article WHERE tsv IS NULL LIMIT 10000);
```

## Alert 3 — Webhook backpressure (`celery_queue_default` > 10000)

**Likely cause:** a slow receiver is causing `deliver` retries to pile up.

**Diagnosis:** inspect `subscriptions_deliverylog` for the noisy `subscription_id`:
```sql
SELECT subscription_id, count(*) AS attempts, max(delivered_at)
FROM subscriptions_deliverylog
WHERE delivered_at > now() - interval '1h' AND error IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC LIMIT 10;
```

**Remediation:**
1. Quarantine: `UPDATE subscriptions_subscription SET is_active = false WHERE id = ...`.
2. Drain queue: monitor `celery -A newsforge inspect active` until empty.
3. Re-enable after the receiver recovers; the unique constraint on `delivery_log` prevents replay duplicates.

## Alert 4 — Beat scheduler stalled

**Likely cause:** `beat` container died and was not restarted; `enqueue_due_feeds` hasn't fired in > 5 minutes.

**Diagnosis:** `docker compose ps beat` — is it running? If yes, check logs for stuck `dispatcher` loop.

**Remediation:** `docker compose restart beat`. Confirm next iteration: `tail -F` until you see `enqueue-due-feeds`.

## Alert 5 — Storage growth (`articles_article` > 80% disk)

**Likely cause:** retention policy not running or window too generous.

**Diagnosis:**
```sql
SELECT pg_size_pretty(pg_total_relation_size('articles_article'));
SELECT date_trunc('month', fetched_at), count(*)
FROM articles_article GROUP BY 1 ORDER BY 1 DESC LIMIT 12;
```

**Remediation:**
1. Run `tasks.scheduler.cleanup_old_articles(days=180)` manually (`celery -A newsforge call tasks.scheduler.cleanup_old_articles --args='[180]'`).
2. Confirm `VACUUM ANALYZE articles_article;` reclaims space.
3. If volumes are truly large, schedule partitioning by `published_at` (see DEPLOYMENT.md scale-out).
