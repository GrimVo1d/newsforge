from __future__ import annotations

from datetime import timedelta

from celery import shared_task
from django.db import connection
from django.utils import timezone

from apps.subscriptions.models import Subscription

MAX_ARTICLES_PER_DIGEST = 100

# Each article is matched with a query parsed in its own language, as in fanout_instant.
_MATCH_SQL = """
SELECT a.id
FROM articles_article a
WHERE NOT a.is_deleted
  AND a.created_at >= %(since)s
  AND a.tsv @@ websearch_to_tsquery(a.language::regconfig, unaccent(%(query)s))
  AND (cardinality(%(feeds)s::bigint[]) = 0 OR a.feed_id = ANY(%(feeds)s))
  AND (
    cardinality(%(tags)s::bigint[]) = 0
    OR EXISTS (
      SELECT 1 FROM tags_articletag t WHERE t.article_id = a.id AND t.tag_id = ANY(%(tags)s)
    )
  )
ORDER BY a.published_at DESC NULLS LAST
LIMIT %(limit)s;
"""


@shared_task(name="tasks.digest.daily_digest", acks_late=True)
def daily_digest() -> dict[str, int]:
    from tasks.notifications import deliver

    now = timezone.now()
    sent = 0
    for sub in Subscription.objects.filter(is_active=True, interval=Subscription.Interval.DAILY):
        since = sub.last_notified_at or now - timedelta(hours=24)
        with connection.cursor() as cur:
            cur.execute(
                _MATCH_SQL,
                {
                    "query": sub.q,
                    "since": since,
                    "feeds": sub.feeds or [],
                    "tags": sub.tag_ids or [],
                    "limit": MAX_ARTICLES_PER_DIGEST,
                },
            )
            article_ids = [r[0] for r in cur.fetchall()]
        for aid in article_ids:
            deliver.apply_async(args=(sub.id, aid))
            sent += 1
        sub.last_notified_at = now
        sub.save(update_fields=["last_notified_at"])
    return {"deliveries": sent}
