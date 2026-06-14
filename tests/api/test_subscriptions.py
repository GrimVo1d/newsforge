from __future__ import annotations

import socket
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.subscriptions.models import Subscription

pytestmark = pytest.mark.django_db

URL = "/api/v1/subscriptions/"
HOOK = "https://hooks.example.internal/nf"


@pytest.fixture(autouse=True)
def dns():
    table = {"hooks.example.internal": "93.184.216.34", "evil.example.internal": "10.0.0.7"}
    real = socket.getaddrinfo

    def fake(host, port, *args, **kwargs):
        if not host.endswith(".example.internal"):
            return real(host, port, *args, **kwargs)  # e.g. the database, from other threads
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


def test_subscriptions_per_user_are_capped(user_api, settings):
    settings.MAX_SUBSCRIPTIONS_PER_USER = 2
    body = {"name": "mail", "q": "django", "delivery": "email", "email_to": "me@example.internal"}
    assert user_api.post(URL, body, format="json").status_code == 201
    assert user_api.post(URL, body, format="json").status_code == 201
    resp = user_api.post(URL, body, format="json")
    assert resp.status_code == 400
    assert "at most 2" in str(resp.json())


def test_rejected_webhook_url_does_not_reveal_addresses(user_api):
    resp = user_api.post(URL, _webhook(webhook_url="https://evil.example.internal/"), format="json")
    assert resp.status_code == 400
    assert "10.0.0.7" not in str(resp.json())


def test_filter_ids_must_exist(user_api, feed):
    from apps.tags.models import Tag

    tag = Tag.objects.create(name="Python", slug="python")
    for field, bad in (("feeds", 2**63), ("tag_ids", 2**63), ("feeds", 999), ("tag_ids", 999)):
        resp = user_api.post(URL, _webhook(**{field: [bad]}), format="json")
        assert resp.status_code == 400, (field, bad)
    feed.is_deleted = True
    feed.save()
    assert user_api.post(URL, _webhook(feeds=[feed.id]), format="json").status_code == 400
    resp = user_api.post(URL, _webhook(tag_ids=[tag.id, tag.id]), format="json")
    assert resp.status_code == 201
    assert resp.json()["tag_ids"] == [tag.id]


def test_put_without_filters_clears_them(user_api, feed):
    body = {"name": "m", "q": "django", "delivery": "email", "email_to": "me@example.internal"}
    sub_id = user_api.post(URL, {**body, "feeds": [feed.id]}, format="json").json()["id"]
    resp = user_api.put(f"{URL}{sub_id}/", body, format="json")
    assert resp.status_code == 200
    assert resp.json()["feeds"] == []
    resp = user_api.patch(f"{URL}{sub_id}/", {"feeds": [feed.id]}, format="json")
    assert user_api.patch(f"{URL}{sub_id}/", {"name": "n"}, format="json").json()["feeds"] == [
        feed.id
    ]


def test_accounts_per_target_are_capped(db, settings):
    from django.contrib.auth import get_user_model
    from rest_framework.test import APIClient

    settings.MAX_ACCOUNTS_PER_TARGET = 2
    clients = []
    for n in range(4):
        client = APIClient()
        client.force_authenticate(get_user_model().objects.create_user(username=f"u{n}"))
        clients.append(client)
    mail = {"name": "m", "q": "x", "delivery": "email", "email_to": "victim@example.internal"}
    assert clients[0].post(URL, mail, format="json").status_code == 201
    assert clients[0].post(URL, mail, format="json").status_code == 201  # same account: fine
    assert clients[1].post(URL, mail, format="json").status_code == 201
    shouted = {**mail, "email_to": "VICTIM@example.internal"}
    resp = clients[2].post(URL, shouted, format="json")
    assert resp.status_code == 400
    assert "other accounts" in str(resp.json())

    assert clients[2].post(URL, _webhook(), format="json").status_code == 201
    assert clients[3].post(URL, _webhook(), format="json").status_code == 201
    own = clients[0].post(URL, {**mail, "email_to": "me@example.internal"}, format="json")
    switched = clients[0].patch(
        f"{URL}{own.json()['id']}/", {"delivery": "webhook", "webhook_url": HOOK}, format="json"
    )
    assert switched.status_code == 400


@pytest.mark.django_db(transaction=True)
def test_subscription_cap_holds_under_concurrency(user, settings, monkeypatch):
    import threading
    import time

    from django.db import connection
    from django.db.models import QuerySet
    from rest_framework.test import APIClient

    settings.MAX_SUBSCRIPTIONS_PER_USER = 1
    real_count = QuerySet.count

    def slow_count(self):
        n = real_count(self)
        if self.model is Subscription:
            time.sleep(0.3)  # widen the check-then-insert window
        return n

    monkeypatch.setattr(QuerySet, "count", slow_count)
    body = {"name": "m", "q": "django", "delivery": "email", "email_to": "me@example.internal"}
    codes: list[int] = []

    def worker():
        client = APIClient()
        client.force_authenticate(user)
        codes.append(client.post(URL, body, format="json").status_code)
        connection.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(codes) == [201, 400]
    assert Subscription.objects.filter(owner=user).count() == 1


def test_deliveries_are_ordered_by_id(user_api, make_article):
    from apps.subscriptions.models import DeliveryLog

    sub_id = user_api.post(URL, _webhook(), format="json").json()["id"]
    first, second = make_article("a"), make_article("b")
    logs = [DeliveryLog.objects.create(subscription_id=sub_id, article=a) for a in (first, second)]
    DeliveryLog.objects.filter(pk=logs[0].pk).update(delivered_at=timezone.now())  # a retry
    rows = user_api.get(f"{URL}{sub_id}/deliveries/").json()["results"]
    assert [r["article_id"] for r in rows] == [second.id, first.id]
