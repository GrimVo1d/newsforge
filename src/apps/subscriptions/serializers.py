from __future__ import annotations

from typing import Any

from django.conf import settings
from rest_framework import serializers

from apps.feeds.validators import SSRFError, assert_public_url
from apps.subscriptions.models import Subscription, new_webhook_secret

MAX_FILTER_IDS = 100


class SubscriptionSerializer(serializers.ModelSerializer[Subscription]):
    q = serializers.CharField(max_length=256)
    feeds = serializers.ListField(
        child=serializers.IntegerField(min_value=1), max_length=MAX_FILTER_IDS, required=False
    )
    tag_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), max_length=MAX_FILTER_IDS, required=False
    )
    webhook_url = serializers.CharField(
        max_length=2048, required=False, allow_null=True, allow_blank=True
    )
    email_to = serializers.EmailField(required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = Subscription
        fields = (
            "id",
            "name",
            "q",
            "feeds",
            "tag_ids",
            "delivery",
            "webhook_url",
            "email_to",
            "interval",
            "is_active",
            "last_notified_at",
            "created_at",
        )
        read_only_fields = ("last_notified_at", "created_at")

    def validate_webhook_url(self, value: str | None) -> str | None:
        if not value:
            return None
        try:
            assert_public_url(value)
        except SSRFError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        def current(field: str) -> Any:
            if field in attrs:
                return attrs[field]
            return getattr(self.instance, field, None)

        delivery = current("delivery")
        if delivery == Subscription.Delivery.WEBHOOK and not current("webhook_url"):
            raise serializers.ValidationError(
                {"webhook_url": "webhook_url is required for delivery=webhook"}
            )
        if delivery == Subscription.Delivery.EMAIL and not current("email_to"):
            raise serializers.ValidationError(
                {"email_to": "email_to is required for delivery=email"}
            )
        return attrs

    def create(self, validated: dict[str, Any]) -> Subscription:
        owner = self.context["request"].user
        limit = settings.MAX_SUBSCRIPTIONS_PER_USER
        if Subscription.objects.filter(owner=owner).count() >= limit:
            raise serializers.ValidationError(
                {"detail": f"at most {limit} subscriptions per user; delete one first"}
            )
        validated["owner"] = owner
        instance = super().create(validated)
        self._ensure_secret(instance)
        return instance

    def update(self, instance: Subscription, validated: dict[str, Any]) -> Subscription:
        instance = super().update(instance, validated)
        self._ensure_secret(instance)
        return instance

    def _ensure_secret(self, instance: Subscription) -> None:
        if instance.delivery == Subscription.Delivery.WEBHOOK and not instance.webhook_secret:
            instance.webhook_secret = new_webhook_secret()
            instance.save(update_fields=["webhook_secret"])
            self._issued_secret = instance.webhook_secret

    def to_representation(self, instance: Subscription) -> dict[str, Any]:
        data = super().to_representation(instance)
        # The secret is returned only in the response that issued it.
        issued = getattr(self, "_issued_secret", None)
        if issued:
            data["webhook_secret"] = issued
        return data


class WebhookSecretSerializer(serializers.Serializer[Any]):
    webhook_secret = serializers.CharField(read_only=True)


class DeliveryLogSerializer(serializers.Serializer[Any]):
    article_id = serializers.IntegerField()
    delivered_at = serializers.DateTimeField()
    succeeded = serializers.BooleanField()
    attempts = serializers.IntegerField()
    http_status = serializers.IntegerField(allow_null=True)
    error = serializers.CharField(allow_null=True)
