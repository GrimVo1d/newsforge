from __future__ import annotations

from typing import Any

from celery import shared_task

from apps.tags.engine import apply_rules_to_article


@shared_task(name="tasks.tags.apply_tag_rules", acks_late=True)
def apply_tag_rules(article_id: int) -> dict[str, Any]:
    assigned = apply_rules_to_article(article_id)
    return {"article_id": article_id, "assigned_tag_ids": assigned}
