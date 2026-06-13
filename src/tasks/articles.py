from __future__ import annotations

from datetime import datetime
from typing import Any

from celery import shared_task

from apps.articles.normalizer import InvalidEntryError, normalize_entry
from apps.articles.services import claim_processing, release_processing, upsert_article
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
    feed_language: str = "simple",
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
            fallback_language=feed_language,
        )
    except InvalidEntryError as exc:
        return {"skipped": str(exc)}
    result = upsert_article(feed_id, entry)
    # Claimed separately from the insert: when queueing failed (or the worker died) after an
    # insert, the redelivered task finds the article unprocessed and queues it then.
    if claim_processing(result.article_id):
        try:
            article_created.send(
                sender="tasks.articles.process_article",
                article_id=result.article_id,
                feed_id=feed_id,
            )
        except Exception:
            release_processing(result.article_id)
            raise
    return {"article_id": result.article_id, "inserted": result.inserted}
