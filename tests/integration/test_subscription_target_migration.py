from __future__ import annotations

from importlib import import_module

import pytest
from django.apps import apps

from apps.subscriptions.models import Subscription

pytestmark = pytest.mark.django_db

migration = import_module("apps.subscriptions.migrations.0005_subscription_target_key")


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
