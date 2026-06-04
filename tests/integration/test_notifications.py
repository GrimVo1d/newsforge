from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta

import httpx
import pytest
from django.core import mail
from django.utils import timezone

from apps.articles.models import Article
from apps.core import safe_http
from apps.subscriptions.models import DeliveryLog, Subscription, new_webhook_secret
from tasks import notifications
from tasks.digest import daily_digest
from tasks.notifications import RetryableDeliveryError, deliver, fanout_instant, sign

pytestmark = pytest.mark.django_db


class FakeReceiver:
    def __init__(self, status: int = 200, exc: Exception | None = None) -> None:
        self.status, self.exc = status, exc
        self.calls: list[dict] = []

    def __call__(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if self.exc:
            raise self.exc
        return safe_http.Response(self.status, httpx.Headers(), b"", url)


@pytest.fixture
def receiver(monkeypatch):
    fake = FakeReceiver()
    monkeypatch.setattr(notifications.safe_http, "request", fake)
    return fake


@pytest.fixture
def hook(user):
    return Subscription.objects.create(
        owner=user,
        name="hook",
        q="django",
        delivery=Subscription.Delivery.WEBHOOK,
        webhook_url="https://hooks.example.internal/nf",
        webhook_secret=new_webhook_secret(),
    )


@pytest.fixture
def article(make_article):
    return make_article("Django 5.2 released", language="english")


def test_signature_format():
    sig = sign("s3cret", 1700000000, b"{}")
    expected = hmac.new(b"s3cret", b"1700000000.{}", hashlib.sha256).hexdigest()
    assert sig == f"sha256={expected}"


def test_webhook_is_signed_and_logged(hook, article, receiver):
    assert deliver(hook.id, article.id) == {"status": 200, "succeeded": True}

    (call,) = receiver.calls
    headers, body = call["headers"], call["content"]
    assert call["max_redirects"] == 0
    assert json.loads(body)["id"] == article.id
    ts = int(headers["X-NF-Timestamp"])
    assert headers["X-NF-Signature"] == sign(hook.webhook_secret, ts, body)

    log = DeliveryLog.objects.get(subscription=hook, article=article)
    assert (log.succeeded, log.http_status, log.attempts) == (True, 200, 1)


def test_successful_delivery_is_not_repeated(hook, article, receiver):
    deliver(hook.id, article.id)
    assert deliver(hook.id, article.id) == {"deduped": True}
    assert len(receiver.calls) == 1


def test_server_errors_are_logged_and_retried(hook, article, receiver):
    receiver.status = 503
    for _ in range(2):
        with pytest.raises(RetryableDeliveryError):
            deliver(hook.id, article.id)
    log = DeliveryLog.objects.get(subscription=hook, article=article)
    assert (log.succeeded, log.http_status, log.attempts) == (False, 503, 2)

    receiver.status = 204
    deliver(hook.id, article.id)
    log.refresh_from_db()
    assert (log.succeeded, log.http_status, log.attempts, log.error) == (True, 204, 3, None)


def test_client_errors_are_final(hook, article, receiver):
    receiver.status = 410
    assert deliver(hook.id, article.id) == {"status": 410, "succeeded": False}
    assert DeliveryLog.objects.get(subscription=hook).error == "receiver answered 410"


def test_network_errors_are_logged_and_retried(hook, article, receiver):
    receiver.exc = httpx.ConnectError("refused")
    with pytest.raises(httpx.ConnectError):
        deliver(hook.id, article.id)
    assert "refused" in DeliveryLog.objects.get(subscription=hook).error


def test_blocked_webhook_is_not_retried(hook, article, receiver):
    receiver.exc = safe_http.UnsafeURLError("resolves to 10.0.0.1")
    assert deliver(hook.id, article.id) == {"status": None, "error": "blocked"}
    assert DeliveryLog.objects.get(subscription=hook).error.startswith("blocked:")


def test_email_subject_cannot_inject_headers(user, make_article):
    article = make_article("Breaking\r\nBcc: victim@example.internal")
    sub = Subscription.objects.create(
        owner=user, name="mail", q="breaking", delivery="email", email_to="me@example.internal"
    )
    deliver(sub.id, article.id)
    (msg,) = mail.outbox
    assert msg.subject == "[newsforge] Breaking Bcc: victim@example.internal"
    assert msg.bcc == []
    assert DeliveryLog.objects.get(subscription=sub).succeeded


def test_fanout_respects_tag_filter(user, hook, make_article, monkeypatch):
    from apps.tags.models import ArticleTag, Tag

    tag = Tag.objects.create(name="Release", slug="release")
    tagged = make_article("Django release notes", language="english")
    untagged = make_article("Django meetup recap", language="english")
    ArticleTag.objects.create(article=tagged, tag=tag)
    hook.tag_ids = [tag.id]
    hook.save()

    queued: list[tuple[int, int]] = []
    monkeypatch.setattr(deliver, "apply_async", lambda args: queued.append(args))
    assert fanout_instant(tagged.id) == {"fanout": 1}
    assert fanout_instant(untagged.id) == {"fanout": 0}
    assert queued == [(hook.id, tagged.id)]


def test_digest_matches_in_article_language(user, make_article, monkeypatch):
    ru = make_article("Вышло обновление DRF", language="russian")
    sub = Subscription.objects.create(
        owner=user,
        name="ru",
        q="обновления",
        delivery="email",
        email_to="me@example.internal",
        interval=Subscription.Interval.DAILY,
    )
    queued: list[tuple[int, int]] = []
    monkeypatch.setattr(deliver, "apply_async", lambda args: queued.append(args))

    assert daily_digest() == {"deliveries": 1}
    assert queued == [(sub.id, ru.id)]

    # The next run only looks at articles created since the previous one.
    sub.refresh_from_db()
    assert sub.last_notified_at is not None
    assert daily_digest() == {"deliveries": 0}

    # A first run without last_notified_at looks back 24 hours.
    sub.last_notified_at = None
    sub.save()
    Article.objects.filter(pk=ru.pk).update(created_at=timezone.now() - timedelta(hours=23))
    assert daily_digest() == {"deliveries": 1}
    sub.last_notified_at = None
    sub.save()
    Article.objects.filter(pk=ru.pk).update(created_at=timezone.now() - timedelta(hours=25))
    assert daily_digest() == {"deliveries": 0}
