from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db

URL = "/api/v1/search/"


@pytest.fixture
def articles(make_article):
    return [
        make_article(
            "Django release notes", summary="Django ships a new release", language="english"
        ),
        make_article(
            "Celery tuning", summary="Django and Celery in production", language="english"
        ),
    ]


def test_search_returns_ranked_hits_with_highlight(api, articles):
    body = api.get(URL, {"q": "django release", "lang": "en"}).json()
    assert body["count"] == 1
    (hit,) = body["results"]
    assert hit["id"] == articles[0].id
    assert "<b>" in hit["highlight"]


def test_search_by_date_and_feed_filter(api, articles, feed):
    body = api.get(URL, {"q": "django", "sort": "date", "feed": f"{feed.id},{feed.id}"}).json()
    assert body["count"] == 2
    assert api.get(URL, {"q": "django", "feed": 999_999}).json()["count"] == 0


def test_empty_query_returns_nothing(api, articles):
    assert api.get(URL).json() == {"count": 0, "results": []}
    assert api.get(URL, {"q": "   "}).json() == {"count": 0, "results": []}


def test_pagination_params(api, articles):
    first = api.get(URL, {"q": "django", "limit": 1}).json()["results"]
    second = api.get(URL, {"q": "django", "limit": 1, "offset": 1}).json()["results"]
    assert len(first) == len(second) == 1
    assert first[0]["id"] != second[0]["id"]


@pytest.mark.parametrize(
    "params",
    [
        {"q": "x", "limit": "0"},
        {"q": "x", "limit": "101"},
        {"q": "x", "limit": "abc"},
        {"q": "x", "offset": "-1"},
        {"q": "x", "offset": "10001"},
        {"q": "x", "feed": "1;DROP"},
        {"q": "x", "feed": "0"},
        {"q": "x", "feed": ",".join(str(i) for i in range(1, 60))},
        {"q": "x", "sort": "random"},
        {"q": "x", "lang": "klingon"},
        {"q": "x", "from": "yesterday"},
        {"q": "x", "from": "2026-05-02T00:00:00Z", "to": "2026-05-01T00:00:00Z"},
        {"q": "x" * 257},
    ],
)
def test_invalid_params_are_rejected(api, params):
    resp = api.get(URL, params)
    assert resp.status_code == 400
    assert resp.json()["code"] == "validation_error"


def test_date_range(api, articles):
    params = {"q": "django", "from": "2000-01-01T00:00:00Z", "to": "2000-01-02T00:00:00Z"}
    assert api.get(URL, params).json()["count"] == 0


def test_fuzzy_fallback_keeps_filters(api, articles, feed):
    # "Djangoo" is not a word in the index, so the trigram fallback answers.
    assert api.get(URL, {"q": "Djangoo releese"}).json()["count"] >= 1
    assert api.get(URL, {"q": "Djangoo releese", "feed": 999_999}).json()["count"] == 0
