# Runbook

Common incidents, how to confirm them and what to do. `/metrics` exports only the default
process and Python collectors, so most checks below are SQL against the database
(`docker compose exec db psql -U nf -d newsforge`) or Celery inspection.

## Many feeds paused

**Symptom:** feeds stop updating; staff see `disabled_until` in the future on many feeds.

**Diagnosis:**
```sql
SELECT split_part(url, '/', 3) AS host, last_status, count(*) AS feeds
FROM feeds_feed
WHERE disabled_until > now()
GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20;
```

**Remediation:**
1. One host, `network_error` / `http_error` → the provider is down or blocks us; wait, or
   check from the worker container.
2. `ssrf_blocked` → the host now resolves to a private address, does not resolve, or
   redirects to such a host (or to plain `http`); this is intended, fix the feed URL. The
   worker log has the resolved address (`apps.core.safe_http`, level `INFO`).
3. To resume a feed early, `POST /api/v1/feeds/{id}/refresh/` as staff: it ends the pause
   and the feed is fetched within a minute. For many feeds at once:
   `UPDATE feeds_feed SET disabled_until = NULL, consecutive_errors = 0, next_fetch_at = now() WHERE id IN (...);`

## Feeds blocked by robots.txt

**Symptom:** `last_status = robots_blocked`. Such feeds are not paused; every interval they
are checked again against the cached robots.txt, without a request to the site.

**Causes:** robots.txt disallows the feed path for the product token of `USER_AGENT` (or for
`*`), or the site answered robots.txt with a `5xx` / was unreachable — that counts as
"disallow everything" for 30 minutes, then robots.txt is fetched again.

**Remediation:** if the site owner changed robots.txt, drop the cached copy (otherwise it is
kept for 24 h):
`python manage.py shell -c "from apps.feeds.robots import invalidate; invalidate('<host>')"`.

## Search misses articles that exist

**Likely cause:** rows with an empty `tsv` (trigger missing after a manual restore), or the
wrong `lang` in the request.

**Diagnosis:**
```sql
SELECT count(*) FROM articles_article WHERE tsv IS NULL AND NOT is_deleted;
SELECT tgname FROM pg_trigger WHERE tgrelid = 'articles_article'::regclass AND NOT tgisinternal;
```

**Remediation:** if the trigger is missing, recreate the function with the `TRIGGER_SQL`
statement from `src/apps/articles/migrations/0006_trigger_search_path_and_full_hash.py` and
the trigger with the `CREATE TRIGGER` part of `TRIGGER_SQL` in
`src/apps/articles/migrations/0001_initial.py`, in psql. Then
rebuild the vectors: `make reindex-tsv`, or in batches on a large table:
```sql
UPDATE articles_article SET title = title
WHERE id IN (SELECT id FROM articles_article WHERE tsv IS NULL LIMIT 10000);
```
If the rows are fine, check that the query uses the article's language (`lang=ru` for
Russian content); see [SEARCH.md](SEARCH.md).

## Webhook deliveries piling up

**Symptom:** the `default` queue grows; one receiver is slow or failing.

**Diagnosis:**
```sql
SELECT subscription_id, count(*) AS pending, sum(attempts) AS attempts, max(delivered_at)
FROM subscriptions_deliverylog
WHERE NOT succeeded AND delivered_at > now() - interval '1 hour'
GROUP BY 1 ORDER BY 3 DESC LIMIT 10;
```
`docker compose exec worker celery -A newsforge inspect scheduled` lists retries waiting
for their countdown.

**Remediation:**
1. Pause the subscription: `UPDATE subscriptions_subscription SET is_active = false WHERE id = ...;`
   — queued and retried tasks for it then end with `DoesNotExist` instead of calling out.
2. Re-enable once the receiver is back. Articles matched while it was paused are not
   re-sent; pairs that never succeeded show `succeeded = false` in the log.

## Beat stopped

**Symptom:** no new articles; `next_fetch_at` of active feeds is in the past.

**Diagnosis:**
```sql
SELECT count(*) FROM feeds_feed
WHERE is_active AND NOT is_deleted AND next_fetch_at < now() - interval '5 minutes'
  AND (disabled_until IS NULL OR disabled_until <= now());
```
`docker compose ps beat` and `docker compose logs --tail 50 beat`.

**Remediation:** `docker compose restart beat`; within a minute the log shows
`Scheduler: Sending due task enqueue-due-feeds`. Run only one `beat`.

## Database growing

**Diagnosis:**
```sql
SELECT pg_size_pretty(pg_total_relation_size('articles_article'));
SELECT date_trunc('month', fetched_at) AS month, count(*)
FROM articles_article GROUP BY 1 ORDER BY 1 DESC LIMIT 12;
```

**Remediation:**
1. Soft-delete older articles sooner than the weekly default of 365 days (one run stops
   after 4 minutes; run it again for a large backlog):
   `docker compose exec worker celery -A newsforge call tasks.scheduler.cleanup_old_articles --args='[180]'`.
2. Soft-deleted rows stay in the table. Remove them through the ORM, which also deletes their
   tags and delivery log rows (the foreign keys have no `ON DELETE CASCADE` in the database):
   `python manage.py shell -c "from apps.articles.models import Article; Article.objects.filter(is_deleted=True).delete()"`,
   then `VACUUM ANALYZE articles_article;`.
3. For sustained volume, partition by `published_at` (see [DEPLOYMENT.md](DEPLOYMENT.md)).
