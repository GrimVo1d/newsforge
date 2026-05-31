"""Signal receivers for article_created — fan out tag-rule + subscription work."""

from __future__ import annotations

from typing import Any

from celery import chain
from django.dispatch import receiver

from apps.articles.signals import article_created


@receiver(article_created)
def on_article_created(sender: Any, *, article_id: int, feed_id: int, **kwargs: Any) -> None:
    from tasks.notifications import fanout_instant
    from tasks.tags import apply_tag_rules

    # Tags first: subscriptions may filter on them.
    chain(apply_tag_rules.si(article_id), fanout_instant.si(article_id)).apply_async()
