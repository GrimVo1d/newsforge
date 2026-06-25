from __future__ import annotations

from importlib import import_module

import pytest
from django.apps import apps

from apps.subscriptions.models import Subscription

pytestmark = pytest.mark.django_db

migration = import_module("apps.subscriptions.migrations.0005_subscription_target_key")
recompute = import_module("apps.subscriptions.migrations.0006_recompute_target_keys")


def test_existing_subscriptions_get_a_target_key(user):
    mail = Subscription.objects.create(
        owner=user, name="m", q="x", delivery="email", email_to="Me+x@Example.internal"
    )
    hook = Subscription.objects.create(
        owner=user, name="h", q="x", delivery="webhook", webhook_url="https://H.example.internal/a/"
    )
    Subscription.objects.update(target_key="")
    migration._backfill(apps, None)
    keys = dict(Subscription.objects.values_list("id", "target_key"))
    assert keys == {mail.id: "mailto:me@example.internal", hook.id: "https://h.example.internal/a"}


def test_keys_of_the_old_normalization_are_recomputed(user):
    hook = Subscription.objects.create(
        owner=user,
        name="h",
        q="x",
        delivery="webhook",
        webhook_url="https://h.example.internal/x/../a",
    )
    Subscription.objects.filter(pk=hook.pk).update(target_key="https://h.example.internal/x/../a")
    recompute._backfill(apps, None)
    hook.refresh_from_db()
    assert hook.target_key == "https://h.example.internal/a"
