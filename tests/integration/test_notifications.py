from __future__ import annotations

import hashlib
import hmac
import json
import smtplib
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
    assert call["discard_body"] is True  # a 2xx with a broken body is still delivered
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


@pytest.mark.parametrize("status", [301, 410])
def test_redirects_and_client_errors_are_final(hook, article, receiver, status):
    receiver.status = status
    assert deliver(hook.id, article.id) == {"status": status, "succeeded": False}
    assert DeliveryLog.objects.get(subscription=hook).error == f"receiver answered {status}"


def test_network_errors_are_logged_and_retried(hook, article, receiver):
    receiver.exc = httpx.ConnectError("refused")
    with pytest.raises(httpx.ConnectError):
        deliver(hook.id, article.id)
    assert DeliveryLog.objects.get(subscription=hook).error == "connection failed"


@pytest.mark.parametrize(
    ("exc", "category"),
    [
        (httpx.ReadTimeout("slow"), "timeout"),
        (safe_http.DeadlineExceededError("https://hooks.example.internal/nf"), "timeout"),
        (RetryableDeliveryError(503), "receiver answered 503"),
        (ConnectionResetError("reset by 10.0.0.7"), "connection failed"),
        (ValueError("secret detail"), "internal error"),
    ],
)
def test_failed_attempts_are_logged_as_a_category(hook, article, receiver, exc, category):
    receiver.exc = exc
    with pytest.raises(type(exc)):
        deliver(hook.id, article.id)
    assert DeliveryLog.objects.get(subscription=hook).error == category


def test_instant_delivery_sets_last_notified_at(hook, article, receiver):
    deliver(hook.id, article.id)
    hook.refresh_from_db()
    assert hook.last_notified_at is not None


def test_failed_delivery_keeps_last_notified_at(hook, article, receiver):
    receiver.status = 410
    deliver(hook.id, article.id)
    hook.refresh_from_db()
    assert hook.last_notified_at is None


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


def test_articles_of_deleted_feeds_are_not_delivered(user, hook, make_article, feed, monkeypatch):
    article = make_article("Django release notes", language="english")
    sub = Subscription.objects.create(
        owner=user,
        name="daily",
        q="django",
        delivery="email",
        email_to="me@example.internal",
        interval=Subscription.Interval.DAILY,
    )
    feed.is_deleted = True
    feed.save()
    queued: list[tuple[int, int]] = []
    monkeypatch.setattr(deliver, "apply_async", lambda args: queued.append(args))
    assert fanout_instant(article.id) == {"fanout": 0}
    assert daily_digest() == {"deliveries": 0}
    assert queued == []
    assert sub.delivery_log.count() == 0


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


def test_digest_window_ends_at_the_run_start(user, make_article, monkeypatch):
    from tasks import digest

    sub = Subscription.objects.create(
        owner=user,
        name="daily",
        q="django",
        delivery="email",
        email_to="me@example.internal",
        interval=Subscription.Interval.DAILY,
    )
    article = make_article("Django release notes", language="english")
    run1 = timezone.now() - timedelta(seconds=5)
    # Stored while the first run was going on: it belongs to the second run only.
    Article.objects.filter(pk=article.pk).update(created_at=run1 + timedelta(seconds=1))
    sub.last_notified_at = run1 - timedelta(days=1)
    sub.save()
    queued: list[tuple[int, int]] = []
    monkeypatch.setattr(deliver, "apply_async", lambda args: queued.append(args))
    for run in (run1, run1 + timedelta(days=1), run1 + timedelta(days=2)):
        monkeypatch.setattr(digest, "_db_now", lambda run=run: run)
        digest.daily_digest()
    assert queued == [(sub.id, article.id)]


def test_fanout_and_delivery_skip_deleted_articles(hook, article, receiver, monkeypatch):
    Article.objects.filter(pk=article.pk).update(is_deleted=True)
    queued: list[tuple[int, int]] = []
    monkeypatch.setattr(deliver, "apply_async", lambda args: queued.append(args))
    assert fanout_instant(article.id) == {"fanout": 0}
    assert deliver(hook.id, article.id) == {"status": None, "error": "gone"}
    assert receiver.calls == []


def test_paused_subscription_ends_cleanly(hook, article, receiver):
    hook.is_active = False
    hook.save()
    assert deliver(hook.id, article.id) == {"status": None, "error": "gone"}
    assert receiver.calls == []
    assert not DeliveryLog.objects.exists()


@pytest.mark.parametrize(
    ("exc", "final"),
    [
        (smtplib.SMTPRecipientsRefused({"me@example.internal": (550, b"no such user")}), True),
        (smtplib.SMTPDataError(554, b"rejected"), True),
        (smtplib.SMTPRecipientsRefused({"me@example.internal": (451, b"try later")}), False),
        (smtplib.SMTPAuthenticationError(535, b"bad credentials"), False),
        (smtplib.SMTPServerDisconnected("gone"), False),
    ],
)
def test_permanent_smtp_rejections_are_final(user, article, monkeypatch, exc, final):
    sub = Subscription.objects.create(
        owner=user, name="m", q="django", delivery="email", email_to="me@example.internal"
    )

    def refuse(**kwargs):
        raise exc

    monkeypatch.setattr(notifications, "send_mail", refuse)
    if final:
        assert deliver(sub.id, article.id)["succeeded"] is False
        log = DeliveryLog.objects.get(subscription=sub)
        assert log.http_status >= 500 and log.leased_until is None
    else:
        with pytest.raises(type(exc)):
            deliver(sub.id, article.id)
        log = DeliveryLog.objects.get(subscription=sub)
        assert log.leased_until is None
        assert log.error == "mail server unavailable"  # never the server's own text


def test_email_log_holds_the_smtp_code(user, article):
    sub = Subscription.objects.create(
        owner=user, name="m", q="django", delivery="email", email_to="me@example.internal"
    )
    assert deliver(sub.id, article.id) == {"status": 250, "succeeded": True}
    assert DeliveryLog.objects.get(subscription=sub).http_status == 250


def test_concurrent_attempt_waits_for_the_lease(hook, article, monkeypatch):
    from tasks.notifications import DeliveryInFlightError

    sends: list[str] = []

    def fake(method, url, **kwargs):
        sends.append("A")
        with pytest.raises(DeliveryInFlightError):  # B starts while A waits for the receiver
            deliver(hook.id, article.id)
        raise httpx.ReadTimeout("A timed out")

    monkeypatch.setattr(notifications.safe_http, "request", fake)
    with pytest.raises(httpx.ReadTimeout):
        deliver(hook.id, article.id)
    assert sends == ["A"]
    log = DeliveryLog.objects.get(subscription=hook, article=article)
    assert (log.succeeded, log.attempts, log.leased_until) == (False, 1, None)

    # B's retry after A released the lease sends once and succeeds.
    monkeypatch.setattr(notifications.safe_http, "request", FakeReceiver())
    assert deliver(hook.id, article.id)["succeeded"] is True


def test_success_is_never_downgraded(hook, article, receiver):
    from tasks.notifications import _record

    deliver(hook.id, article.id)
    _record(hook.id, article.id, succeeded=False, http_status=None, error="late failure")
    log = DeliveryLog.objects.get(subscription=hook, article=article)
    assert (log.succeeded, log.error, log.attempts) == (True, None, 1)


def test_expired_lease_is_taken_over(hook, article, receiver):
    DeliveryLog.objects.create(
        subscription=hook,
        article=article,
        attempts=1,
        leased_until=timezone.now() - timedelta(seconds=1),  # the sender died
    )
    assert deliver(hook.id, article.id)["succeeded"] is True
    assert DeliveryLog.objects.get(subscription=hook).attempts == 2
