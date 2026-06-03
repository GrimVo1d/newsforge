from __future__ import annotations

from datetime import datetime
from typing import Any

from celery import shared_task

from apps.articles.normalizer import InvalidEntryError, normalize_entry
from apps.articles.services import upsert_article
from apps.articles.signals import article_created


@shared_task(name="tasks.articles.process_article", acks_late=True)
def process_article(
    *,
    feed_id: int,
    url: str,
    title: str,
    summary: str = "",
    body: str = "",
    guid: str = "",
    author: str | None = None,
    published_at: str | None = None,
) -> dict[str, Any]:
    pub = datetime.fromisoformat(published_at) if published_at else None
    try:
        entry = normalize_entry(
            url=url,
            title=title,
            summary=summary,
            body=body,
            guid=guid,
            author=author,
            published_at=pub,
        )
    except InvalidEntryError as exc:
        return {"skipped": str(exc)}
    result = upsert_article(feed_id, entry)
    if result.inserted:
        article_created.send(
            sender="tasks.articles.process_article",
            article_id=result.article_id,
            feed_id=feed_id,
        )
    return {"article_id": result.article_id, "inserted": result.inserted}
