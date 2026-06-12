from __future__ import annotations

import socket
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.feeds.models import Feed
from apps.tags.models import ArticleTag, Tag, TagRule

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def public_dns():
    def fake(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    with patch("apps.core.safe_http.socket.getaddrinfo", side_effect=fake):
        yield


@pytest.fixture
def tag(db):
    return Tag.objects.create(name="Python", slug="python")


NEW_FEED = {"url": "https://blog.example.internal/rss", "language": "english"}


def test_everyone_reads_feeds_without_crawl_state(api, user_api, feed):
    for client in (api, user_api):
        (row,) = client.get("/api/v1/feeds/").json()["results"]
        assert set(row) == {"id", "url", "site_url", "title", "language", "created_at"}


def test_inactive_feeds_are_hidden_from_non_staff(api, staff_api, feed):
    feed.is_active = False
    feed.save()
    assert api.get("/api/v1/feeds/").json()["count"] == 0
    assert api.get(f"/api/v1/feeds/{feed.id}/").status_code == 404
    (row,) = staff_api.get("/api/v1/feeds/").json()["results"]
    assert row["last_status"] == ""


@pytest.mark.parametrize("client_name, expected", [("api", 401), ("user_api", 403)])
def test_only_staff_change_feeds(request, feed, client_name, expected):
    client = request.getfixturevalue(client_name)
    assert client.post("/api/v1/feeds/", NEW_FEED, format="json").status_code == expected
    assert client.patch(f"/api/v1/feeds/{feed.id}/", {"title": "x"}).status_code == expected
    assert client.delete(f"/api/v1/feeds/{feed.id}/").status_code == expected
    assert client.post(f"/api/v1/feeds/{feed.id}/refresh/").status_code == expected
    feed.refresh_from_db()
    assert not feed.is_deleted


def test_staff_manage_feeds(staff_api):
    resp = staff_api.post("/api/v1/feeds/", NEW_FEED, format="json")
    assert resp.status_code == 201, resp.json()
    feed_id = resp.json()["id"]
    assert staff_api.post(f"/api/v1/feeds/{feed_id}/refresh/").status_code == 202
    assert staff_api.delete(f"/api/v1/feeds/{feed_id}/").status_code == 204
    assert Feed.objects.get(pk=feed_id).is_deleted


def test_deleted_feed_can_be_added_again(staff_api, feed):
    feed.etag, feed.consecutive_errors, feed.last_status = '"old"', 4, "http_error"
    feed.save()
    assert staff_api.delete(f"/api/v1/feeds/{feed.id}/").status_code == 204
    resp = staff_api.post("/api/v1/feeds/", {"url": feed.url, "language": "russian"}, format="json")
    assert resp.status_code == 201, resp.json()
    assert resp.json()["id"] == feed.id
    feed.refresh_from_db()
    assert (feed.is_deleted, feed.is_active, feed.language) == (False, True, "russian")
    assert (feed.etag, feed.consecutive_errors, feed.last_status) == (None, 0, "")


def test_live_feed_url_must_be_unique(staff_api, feed):
    resp = staff_api.post("/api/v1/feeds/", {"url": feed.url}, format="json")
    assert resp.status_code == 400
    other = Feed.objects.create(url="https://other.example.internal/rss")
    resp = staff_api.patch(f"/api/v1/feeds/{other.id}/", {"url": feed.url}, format="json")
    assert resp.status_code == 400


def test_changing_the_url_resets_crawl_state(staff_api, feed):
    feed.etag, feed.last_modified, feed.consecutive_errors = '"v1"', "yesterday", 6
    feed.disabled_until = timezone.now() + timedelta(hours=3)
    feed.save()
    resp = staff_api.patch(
        f"/api/v1/feeds/{feed.id}/", {"url": "https://moved.example.internal/rss"}, format="json"
    )
    assert resp.status_code == 200, resp.json()
    feed.refresh_from_db()
    assert (feed.etag, feed.last_modified, feed.consecutive_errors) == (None, None, 0)
    assert feed.disabled_until is None
    assert feed.next_fetch_at <= timezone.now()


def test_refresh_ends_a_pause(staff_api, feed):
    feed.disabled_until = timezone.now() + timedelta(hours=3)
    feed.save()
    assert staff_api.post(f"/api/v1/feeds/{feed.id}/refresh/").status_code == 202
    feed.refresh_from_db()
    assert feed.disabled_until is None


def test_feed_interval_has_a_floor(staff_api):
    resp = staff_api.post("/api/v1/feeds/", {**NEW_FEED, "interval_seconds": 10}, format="json")
    assert resp.status_code == 400


@pytest.mark.parametrize("client_name, expected", [("api", 401), ("user_api", 403)])
def test_only_staff_change_tags(request, tag, client_name, expected):
    client = request.getfixturevalue(client_name)
    assert client.get("/api/v1/tags/").status_code == 200
    assert client.post("/api/v1/tags/", {"name": "Go", "slug": "go"}).status_code == expected
    assert client.delete(f"/api/v1/tags/{tag.id}/").status_code == expected
    assert Tag.objects.filter(pk=tag.id).exists()


def test_tag_slug_is_validated(staff_api, tag):
    assert staff_api.post("/api/v1/tags/", {"name": "A", "slug": "bad slug"}).status_code == 400
    assert staff_api.post("/api/v1/tags/", {"name": "B", "slug": "python"}).status_code == 400
    assert staff_api.post("/api/v1/tags/", {"name": "Go", "slug": "go"}).status_code == 201


@pytest.mark.parametrize("client_name, expected", [("api", 401), ("user_api", 403)])
def test_only_staff_tag_articles(request, make_article, tag, client_name, expected):
    client = request.getfixturevalue(client_name)
    article = make_article("Python 3.13")
    url = f"/api/v1/articles/{article.id}/tags/"
    assert client.post(url, {"tag_id": tag.id}).status_code == expected
    assert not ArticleTag.objects.exists()


def test_staff_tag_articles(staff_api, make_article, tag):
    article = make_article("Python 3.13")
    url = f"/api/v1/articles/{article.id}/tags/"
    assert staff_api.post(url, {"tag_id": tag.id}).status_code == 201
    assert ArticleTag.objects.filter(article=article, tag=tag).exists()
    assert staff_api.delete(url, {"tag_id": tag.id}, format="json").status_code == 204
    assert not ArticleTag.objects.exists()


@pytest.mark.parametrize("client_name, expected", [("api", 401), ("user_api", 403)])
def test_tag_rules_are_staff_only(request, client_name, expected):
    client = request.getfixturevalue(client_name)
    assert client.get("/api/v1/tag-rules/").status_code == expected


def test_staff_manage_tag_rules(staff_api, staff, tag, make_article):
    body = {"name": "py", "keywords": ["python", "django"], "tag": tag.id, "language": "english"}
    resp = staff_api.post("/api/v1/tag-rules/", body, format="json")
    assert resp.status_code == 201, resp.json()
    assert TagRule.objects.get(pk=resp.json()["id"]).owner == staff

    from apps.tags.engine import apply_rules_to_article

    article = make_article("Django tips for Python developers", language="english")
    assert apply_rules_to_article(article.id) == [tag.id]

    bad = {**body, "keywords": []}
    assert staff_api.post("/api/v1/tag-rules/", bad, format="json").status_code == 400
    bad = {**body, "language": "klingon"}
    assert staff_api.post("/api/v1/tag-rules/", bad, format="json").status_code == 400
