from __future__ import annotations

import secrets

from passlib.hash import argon2
from rest_framework import serializers

from apps.subscriptions.models import Subscription


class SubscriptionSerializer(serializers.ModelSerializer):
    webhook_secret = serializers.CharField(read_only=True)

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
            "webhook_secret",
            "interval",
            "is_active",
            "created_at",
        )
        read_only_fields = ("created_at",)

    def validate(self, attrs: dict) -> dict:
        delivery = attrs.get("delivery")
        if delivery == Subscription.Delivery.WEBHOOK and not attrs.get("webhook_url"):
            raise serializers.ValidationError(
                {"code": "missing_webhook_url", "detail": "webhook_url is required for delivery=webhook"}
            )
        if delivery == Subscription.Delivery.EMAIL and not attrs.get("email_to"):
            raise serializers.ValidationError(
                {"code": "missing_email_to", "detail": "email_to is required for delivery=email"}
            )
        return attrs

    def create(self, validated: dict) -> Subscription:
        validated["owner"] = self.context["request"].user
        plaintext_secret = secrets.token_urlsafe(32)
        validated["webhook_secret"] = argon2.hash(plaintext_secret)
        instance = super().create(validated)
        # Attach plaintext on the response only, not the DB column.
        instance.webhook_secret = plaintext_secret
        return instance
