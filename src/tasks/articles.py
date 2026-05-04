from __future__ import annotations

from datetime import datetime

from celery import shared_task

from apps.articles.normalizer import normalize_entry
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
) -> dict:
    pub = datetime.fromisoformat(published_at) if published_at else None
    entry = normalize_entry(
        url=url,
        title=title,
        summary=summary,
        body=body,
        guid=guid,
        author=author,
        published_at=pub,
    )
    result = upsert_article(feed_id, entry)
    if result.inserted:
        article_created.send(
            sender="tasks.articles.process_article",
            article_id=result.article_id,
            feed_id=feed_id,
        )
    return {"article_id": result.article_id, "inserted": result.inserted}
