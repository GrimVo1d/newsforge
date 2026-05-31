from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from apps.subscriptions.models import Subscription

pytestmark = pytest.mark.django_db

URL = "/api/v1/subscriptions/"
HOOK = "https://hooks.example.internal/nf"


@pytest.fixture(autouse=True)
def dns():
    table = {"hooks.example.internal": "93.184.216.34", "evil.example.internal": "10.0.0.7"}

    def fake(host, port, *args, **kwargs):
        if host not in table:
            raise socket.gaierror(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table[host], port))]

    with patch("apps.core.safe_http.socket.getaddrinfo", side_effect=fake):
        yield


def _webhook(**extra):
    return {"name": "hook", "q": "django", "delivery": "webhook", "webhook_url": HOOK, **extra}


def test_requires_authentication(api):
    assert api.get(URL).status_code == 401


def test_webhook_secret_is_shown_once(user_api):
    created = user_api.post(URL, _webhook(), format="json")
    assert created.status_code == 201, created.json()
    secret = created.json()["webhook_secret"]
    assert len(secret) >= 40

    sub = Subscription.objects.get(pk=created.json()["id"])
    assert sub.webhook_secret == secret

    detail = user_api.get(f"{URL}{sub.pk}/").json()
    assert "webhook_secret" not in detail
    listing = user_api.get(URL).json()["results"]
    assert all("webhook_secret" not in row for row in listing)


def test_rotate_secret(user_api):
    sub_id = user_api.post(URL, _webhook(), format="json").json()["id"]
    old = Subscription.objects.get(pk=sub_id).webhook_secret
    resp = user_api.post(f"{URL}{sub_id}/rotate-secret/")
    assert resp.status_code == 200
    assert resp.json()["webhook_secret"] != old
    assert Subscription.objects.get(pk=sub_id).webhook_secret == resp.json()["webhook_secret"]


def test_rotate_secret_rejects_email_subscription(user_api):
    body = {"name": "mail", "q": "django", "delivery": "email", "email_to": "me@example.internal"}
    sub_id = user_api.post(URL, body, format="json").json()["id"]
    assert user_api.post(f"{URL}{sub_id}/rotate-secret/").status_code == 400


@pytest.mark.parametrize(
    "webhook_url",
    [
        "https://evil.example.internal/hook",
        "https://nowhere.example.internal/hook",
        "file:///etc/passwd",
        "https://hooks.example.internal:8080/nf",
        "http://hooks.example.internal/nf",
    ],
)
def test_webhook_url_must_be_public(user_api, webhook_url):
    resp = user_api.post(URL, _webhook(webhook_url=webhook_url), format="json")
    assert resp.status_code == 400
    assert "webhook_url" in str(resp.json()["detail"])


@pytest.mark.parametrize("email", ["not-an-email", "a@b.internal\r\nBcc: x@y.internal"])
def test_email_to_is_validated(user_api, email):
    body = {"name": "mail", "q": "django", "delivery": "email", "email_to": email}
    assert user_api.post(URL, body, format="json").status_code == 400


def test_partial_update_keeps_delivery_rules(user_api):
    sub_id = user_api.post(URL, _webhook(), format="json").json()["id"]
    resp = user_api.patch(f"{URL}{sub_id}/", {"webhook_url": None}, format="json")
    assert resp.status_code == 400
    resp = user_api.patch(f"{URL}{sub_id}/", {"name": "renamed"}, format="json")
    assert resp.status_code == 200
    assert "webhook_secret" not in resp.json()


def test_switching_to_webhook_issues_secret(user_api):
    body = {"name": "mail", "q": "django", "delivery": "email", "email_to": "me@example.internal"}
    sub_id = user_api.post(URL, body, format="json").json()["id"]
    resp = user_api.patch(
        f"{URL}{sub_id}/", {"delivery": "webhook", "webhook_url": HOOK}, format="json"
    )
    assert resp.status_code == 200
    assert resp.json()["webhook_secret"] == Subscription.objects.get(pk=sub_id).webhook_secret


def test_filters_are_bounded(user_api):
    resp = user_api.post(URL, _webhook(feeds=list(range(1, 102))), format="json")
    assert resp.status_code == 400
    resp = user_api.post(URL, _webhook(tag_ids=[0]), format="json")
    assert resp.status_code == 400
    resp = user_api.post(URL, _webhook(q="x" * 257), format="json")
    assert resp.status_code == 400


def test_subscriptions_are_private(user_api, staff_api):
    sub_id = user_api.post(URL, _webhook(), format="json").json()["id"]
    assert staff_api.get(f"{URL}{sub_id}/").status_code == 404
    assert staff_api.post(f"{URL}{sub_id}/rotate-secret/").status_code == 404
    assert staff_api.get(URL).json()["count"] == 0


def test_deliveries_endpoint(user_api, make_article):
    from apps.subscriptions.models import DeliveryLog

    sub_id = user_api.post(URL, _webhook(), format="json").json()["id"]
    article = make_article("Django news")
    DeliveryLog.objects.create(
        subscription_id=sub_id, article=article, succeeded=False, http_status=503, error="x"
    )
    rows = user_api.get(f"{URL}{sub_id}/deliveries/").json()["results"]
    assert rows == [
        {
            "article_id": article.id,
            "delivered_at": rows[0]["delivered_at"],
            "succeeded": False,
            "attempts": 1,
            "http_status": 503,
            "error": "x",
        }
    ]
