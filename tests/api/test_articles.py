from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.articles.models import Article
from apps.tags.models import ArticleTag, Tag

pytestmark = pytest.mark.django_db

URL = "/api/v1/articles/"


@pytest.fixture
def articles(make_article):
    old = make_article("Old Django news", language="english")
    new = make_article("Новости Python", language="russian")
    now = timezone.now()
    Article.objects.filter(pk=old.pk).update(published_at=now - timedelta(days=2))
    Article.objects.filter(pk=new.pk).update(published_at=now)
    return old, new


def test_list_is_newest_first_and_public(api, articles):
    old, new = articles
    rows = api.get(URL).json()["results"]
    assert [r["id"] for r in rows] == [new.id, old.id]
    assert "body" not in rows[0]


def test_detail_includes_body_and_tags(api, articles):
    old, _ = articles
    tag = Tag.objects.create(name="Django", slug="django")
    ArticleTag.objects.create(article=old, tag=tag)
    body = api.get(f"{URL}{old.id}/").json()
    assert body["tags"] == ["django"]
    assert "body" in body


def test_filters(api, articles, feed):
    old, new = articles
    tag = Tag.objects.create(name="Django", slug="django")
    ArticleTag.objects.create(article=old, tag=tag)

    def ids(**params):
        return [r["id"] for r in api.get(URL, params).json()["results"]]

    assert ids(tag="django") == [old.id]
    assert ids(language="russian") == [new.id]
    assert ids(language="RU") == [new.id]
    assert ids(language="en") == [old.id]
    assert ids(feed=feed.id) == [new.id, old.id]
    assert ids(feed=999_999) == []
    since = (timezone.now() - timedelta(days=1)).isoformat()
    assert ids(published_after=since) == [new.id]
    assert ids(published_before=since) == [old.id]


def test_deleted_articles_and_feeds_are_hidden(api, articles, feed):
    old, new = articles
    Article.objects.filter(pk=old.pk).update(is_deleted=True)
    assert [r["id"] for r in api.get(URL).json()["results"]] == [new.id]
    feed.is_deleted = True
    feed.save()
    assert api.get(URL).json()["count"] == 0


def test_articles_are_read_only(staff_api, articles):
    assert staff_api.post(URL, {"title": "x"}).status_code == 405
    assert staff_api.delete(f"{URL}{articles[0].id}/").status_code == 405
