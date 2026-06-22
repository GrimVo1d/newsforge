"""The error envelope {"code": ..., "detail": ...} on every kind of failure."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

SUBS = "/api/v1/subscriptions/"


def _envelope(resp, status: int, code: str):
    assert resp.status_code == status, resp.content[:300]
    assert resp["Content-Type"].startswith("application/json")
    body = resp.json()
    assert set(body) == {"code", "detail"}, body
    assert body["code"] == code, body
    return body["detail"]


def test_not_found_from_views_and_unknown_paths(api):
    assert isinstance(_envelope(api.get("/api/v1/feeds/987654/"), 404, "not_found"), str)
    assert isinstance(_envelope(api.get("/api/v1/articles/987654/"), 404, "not_found"), str)
    _envelope(api.get("/api/v1/does-not-exist/"), 404, "not_found")
    _envelope(api.get("/api/v1/articles/99999999999999999999999/"), 404, "not_found")


def test_request_errors_have_specific_codes(user_api):
    _envelope(user_api.post(SUBS, data="{bad", content_type="application/json"), 400, "parse_error")
    _envelope(
        user_api.post(SUBS, data="x", content_type="text/plain"), 415, "unsupported_media_type"
    )
    _envelope(user_api.put(SUBS, {}, format="json"), 405, "method_not_allowed")


def test_auth_errors(api):
    _envelope(api.get(SUBS), 401, "not_authenticated")
    detail = _envelope(api.get(SUBS, HTTP_AUTHORIZATION="Bearer garbage"), 401, "token_not_valid")
    assert isinstance(detail, str)


def test_permission_denied(user_api):
    _envelope(user_api.post("/api/v1/tags/", {"name": "x", "slug": "x"}), 403, "permission_denied")


def test_validation_errors_map_fields_to_messages(user_api, settings):
    detail = _envelope(user_api.post(SUBS, {"name": "x"}, format="json"), 400, "validation_error")
    assert set(detail) >= {"q", "delivery"}
    assert all(isinstance(v, list) for v in detail.values())

    settings.MAX_SUBSCRIPTIONS_PER_USER = 0
    body = {"name": "m", "q": "x", "delivery": "email", "email_to": "me@example.internal"}
    detail = _envelope(user_api.post(SUBS, body, format="json"), 400, "validation_error")
    assert list(detail) == ["non_field_errors"]
    assert "at most 0" in detail["non_field_errors"][0]


def test_throttled_has_retry_after(api, monkeypatch):
    from django.core.cache import cache
    from rest_framework.throttling import ScopedRateThrottle

    cache.clear()
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {"search": "1/min"})
    api.get("/api/v1/search/", {"q": "x"})
    resp = api.get("/api/v1/search/", {"q": "x"})
    cache.clear()
    assert isinstance(_envelope(resp, 429, "rate_limited"), str)
    assert "Retry-After" in resp


def test_unhandled_errors_are_json(monkeypatch):
    from apps.search import views

    def boom(**kwargs):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(views, "run_search", boom)
    resp = APIClient(raise_request_exception=False).get("/api/v1/search/", {"q": "x"})
    detail = _envelope(resp, 500, "server_error")
    assert "exploded" not in detail


def test_disallowed_host_is_json(settings):
    settings.ALLOWED_HOSTS = ["news.example.internal"]
    resp = APIClient().get("/api/v1/feeds/", HTTP_HOST="attacker.example.internal")
    assert _envelope(resp, 400, "bad_request") == "Bad request."


def test_list_offset_is_capped(api):
    detail = _envelope(api.get("/api/v1/articles/", {"offset": 10_001}), 400, "validation_error")
    assert "offset" in detail
    assert api.get("/api/v1/articles/", {"offset": 10_000}).status_code == 200


def test_concurrent_tag_slug_is_a_validation_error(staff_api, monkeypatch):
    from apps.tags.models import Tag
    from apps.tags.serializers import TagSerializer

    Tag.objects.create(name="Python", slug="python")
    # The uniqueness check passed in both requests; the insert decides.
    monkeypatch.setattr(TagSerializer, "validate_slug", lambda self, value: value)
    resp = staff_api.post("/api/v1/tags/", {"name": "Python 2", "slug": "python"}, format="json")
    assert "slug" in _envelope(resp, 400, "validation_error")


def test_tagging_twice_answers_200(staff_api, make_article):
    from apps.tags.models import Tag

    tag = Tag.objects.create(name="Python", slug="python")
    article = make_article("Python news")
    url = f"/api/v1/articles/{article.id}/tags/"
    assert staff_api.post(url, {"tag_id": tag.id}, format="json").status_code == 201
    assert staff_api.post(url, {"tag_id": tag.id}, format="json").status_code == 200
    assert set(staff_api.get(f"/api/v1/tags/{tag.id}/").json()) == {"id", "name", "slug"}


def _schema(api):
    return api.get("/api/schema/", {"format": "json"}).json()


def test_schema_describes_the_real_parameters_and_fields(api):
    schema = _schema(api)
    search = {p["name"] for p in schema["paths"]["/api/v1/search/"]["get"]["parameters"]}
    assert {"q", "lang", "from", "to", "feed"} <= search
    assert not {"date_from", "date_to"} & search

    def component(op, part):
        ref = part["content"]["application/json"]["schema"]["$ref"]
        return schema["components"]["schemas"][ref.rsplit("/", 1)[1]]["properties"]

    feed_post = schema["paths"]["/api/v1/feeds/"]["post"]
    writable = {
        k
        for k, v in component(feed_post, feed_post["requestBody"]).items()
        if not v.get("readOnly")
    }
    assert {"url", "interval_seconds", "is_active", "language"} <= writable

    sub_post = schema["paths"]["/api/v1/subscriptions/"]["post"]
    assert "webhook_secret" in component(sub_post, sub_post["responses"]["201"])


def test_search_lang_is_case_insensitive(api):
    assert api.get("/api/v1/search/", {"q": "x", "lang": "EN"}).status_code == 200
    assert api.get("/api/v1/search/", {"q": "x", "lang": "Russian"}).status_code == 200
