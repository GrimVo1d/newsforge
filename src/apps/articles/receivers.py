"""Signal receivers for article_created — fan out tag-rule + subscription work."""

from __future__ import annotations

from django.dispatch import receiver

from apps.articles.signals import article_created


@receiver(article_created)
def on_article_created(sender, *, article_id: int, feed_id: int, **kwargs) -> None:
    from tasks.notifications import fanout_instant
    from tasks.tags import apply_tag_rules

    apply_tag_rules.apply_async(args=[article_id])
    fanout_instant.apply_async(args=[article_id])
