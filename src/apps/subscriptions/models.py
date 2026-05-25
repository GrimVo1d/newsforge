from __future__ import annotations

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models


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
    webhook_secret = models.CharField(max_length=255, null=True, blank=True)  # argon2 hash
    interval = models.CharField(max_length=16, choices=Interval.choices, default=Interval.INSTANT)
    last_notified_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "subscriptions_subscription"

    def __str__(self) -> str:
        return self.name


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
    delivered_at = models.DateTimeField(auto_now_add=True)
    http_status = models.SmallIntegerField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "subscriptions_deliverylog"
        constraints = [
            models.UniqueConstraint(fields=["subscription", "article"], name="delivery_log_unique")
        ]
