from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model


@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(username="alice", password="passpasspass")


@pytest.fixture
def feed(db):
    from apps.feeds.models import Feed

    return Feed.objects.create(url="https://example.internal/feed.xml", language="english")


@pytest.fixture
def make_article(feed):
    from apps.articles.models import Article
    from apps.articles.normalizer import normalize_entry
    from apps.articles.services import upsert_article

    counter = iter(range(1, 10_000))

    def make(title: str, *, summary: str = "", language: str | None = None, feed_id=None):
        n = next(counter)
        entry = normalize_entry(
            url=f"https://example.internal/p/{n}",
            title=title,
            summary=summary,
            body="",
            guid=f"guid-{n}",
        )
        if language:
            entry.language = language
        result = upsert_article(feed_id or feed.id, entry)
        return Article.objects.get(pk=result.article_id)

    return make
