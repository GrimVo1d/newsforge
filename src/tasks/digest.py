from __future__ import annotations

from datetime import timedelta

from celery import shared_task
from django.db import connection
from django.utils import timezone

from apps.subscriptions.models import Subscription

_MATCH_SQL = """
WITH q AS (
  SELECT websearch_to_tsquery('simple'::regconfig, unaccent(%(query)s)) AS tsq
)
SELECT a.id
FROM articles_article a, q
WHERE NOT a.is_deleted
  AND a.tsv @@ q.tsq
  AND a.created_at >= %(since)s
  AND (cardinality(%(feeds)s::bigint[]) = 0 OR a.feed_id = ANY(%(feeds)s))
ORDER BY a.published_at DESC NULLS LAST
LIMIT 100;
"""


@shared_task(name="tasks.digest.daily_digest", acks_late=True)
def daily_digest() -> dict:
    from tasks.notifications import deliver

    since = timezone.now() - timedelta(hours=24)
    sent = 0
    for sub in Subscription.objects.filter(is_active=True, interval=Subscription.Interval.DAILY):
        with connection.cursor() as cur:
            cur.execute(
                _MATCH_SQL,
                {"query": sub.q, "since": since, "feeds": sub.feeds or []},
            )
            article_ids = [r[0] for r in cur.fetchall()]
        for aid in article_ids:
            deliver.apply_async(args=[sub.id, aid])
            sent += 1
        sub.last_notified_at = timezone.now()
        sub.save(update_fields=["last_notified_at"])
    return {"deliveries": sent}
