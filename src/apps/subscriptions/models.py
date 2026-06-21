from __future__ import annotations

import secrets
from typing import Any

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.subscriptions.targets import target_key

WEBHOOK_SECRET_BYTES = 32


def new_webhook_secret() -> str:
    return secrets.token_urlsafe(WEBHOOK_SECRET_BYTES)


class Subscription(models.Model):
    class Delivery(models.TextChoices):
        WEBHOOK = "webhook", "webhook"
        EMAIL = "email", "email"

    class Interval(models.TextChoices):
        INSTANT = "instant", "instant"
        DAILY = "daily", "daily"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscriptions",
        db_column="owner_id",
    )
    name = models.CharField(max_length=120)
    q = models.TextField()
    feeds = ArrayField(models.BigIntegerField(), default=list, blank=True)
    tag_ids = ArrayField(models.BigIntegerField(), default=list, blank=True)
    delivery = models.CharField(max_length=16, choices=Delivery.choices)
    webhook_url = models.TextField(null=True, blank=True)
    email_to = models.TextField(null=True, blank=True)
    # The target in one spelling (apps.subscriptions.targets), kept in sync by save().
    target_key = models.TextField(blank=True, default="", db_index=True)
    # HMAC key for webhook signatures. Stored as plaintext because signing needs it; it is
    # shown to the owner once (on create / rotate) and never serialized afterwards.
    webhook_secret = models.CharField(max_length=255, null=True, blank=True)
    interval = models.CharField(max_length=16, choices=Interval.choices, default=Interval.INSTANT)
    last_notified_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "subscriptions_subscription"

    def __str__(self) -> str:
        return self.name

    def target(self) -> str | None:
        return self.email_to if self.delivery == self.Delivery.EMAIL else self.webhook_url

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.target_key = target_key(self.delivery, self.target())
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "target_key" not in update_fields:
            kwargs["update_fields"] = [*update_fields, "target_key"]
        super().save(*args, **kwargs)


class DeliveryLog(models.Model):
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name="delivery_log",
        db_column="subscription_id",
    )
    article = models.ForeignKey(
        "articles.Article",
        on_delete=models.CASCADE,
        related_name="delivery_log",
        db_column="article_id",
    )
    # Time of the last attempt; the row is updated on every retry.
    delivered_at = models.DateTimeField(auto_now=True)
    succeeded = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=1)
    # HTTP status of the webhook answer, or the SMTP reply code for email (250 when accepted).
    http_status = models.SmallIntegerField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    # Set while a worker is sending; another task for the same pair waits until it ends.
    leased_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "subscriptions_deliverylog"
        constraints = [
            models.UniqueConstraint(fields=["subscription", "article"], name="delivery_log_unique")
        ]
