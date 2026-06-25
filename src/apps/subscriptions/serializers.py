from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from rest_framework import serializers

from apps.feeds.models import Feed
from apps.feeds.validators import SSRFError, assert_public_url
from apps.subscriptions.models import Subscription, new_webhook_secret
from apps.subscriptions.targets import target_key
from apps.tags.models import Tag

MAX_FILTER_IDS = 100
MAX_ID = 2**63 - 1  # bigint


def _target_field(delivery: str) -> str:
    return "email_to" if delivery == Subscription.Delivery.EMAIL else "webhook_url"


class SubscriptionSerializer(serializers.ModelSerializer[Subscription]):
    q = serializers.CharField(max_length=256)
    feeds = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=MAX_ID),
        max_length=MAX_FILTER_IDS,
        required=False,
    )
    tag_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=MAX_ID),
        max_length=MAX_FILTER_IDS,
        required=False,
    )
    webhook_url = serializers.CharField(
        max_length=2048, required=False, allow_null=True, allow_blank=True
    )
    email_to = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    # Documented here so that the schema shows it; to_representation drops it unless issued.
    webhook_secret = serializers.CharField(
        read_only=True,
        required=False,
        help_text="Returned only in the response that issues it (create, switch to webhook).",
    )

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
            "webhook_secret",
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

    def validate_email_to(self, value: str | None) -> str | None:
        if not value:
            return None
        local, _, domain = value.rpartition("@")
        # Valid by RFC 5321 but needless here, and each spelling would be another target.
        if '"' in local or domain.startswith("["):
            raise serializers.ValidationError(
                "quoted local parts and address literals are not supported"
            )
        return value

    def validate_feeds(self, value: list[int]) -> list[int]:
        found = set(
            Feed.objects.filter(pk__in=value, is_deleted=False).values_list("pk", flat=True)
        )
        missing = sorted(set(value) - found)
        if missing:
            raise serializers.ValidationError(f"unknown feed ids: {missing}")
        return sorted(set(value))

    def validate_tag_ids(self, value: list[int]) -> list[int]:
        found = set(Tag.objects.filter(pk__in=value).values_list("pk", flat=True))
        missing = sorted(set(value) - found)
        if missing:
            raise serializers.ValidationError(f"unknown tag ids: {missing}")
        return sorted(set(value))

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not self.partial:
            # A full update replaces the filters too; leaving them out clears them.
            attrs.setdefault("feeds", [])
            attrs.setdefault("tag_ids", [])

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

    def _check_target(self, owner_id: int, delivery: str, target: str | None) -> None:
        """Bound how many accounts can point their subscriptions at one address or URL.

        Spelling variants of a target share one key, and the key is locked until the end of
        the transaction, so parallel requests from different accounts cannot all pass.
        """
        key = target_key(delivery, target)
        if not key:
            return
        if connection.vendor == "postgresql":
            with connection.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s));", [key])
        others = Subscription.objects.exclude(owner_id=owner_id).filter(target_key=key)
        limit = settings.MAX_ACCOUNTS_PER_TARGET
        if others.values("owner_id").distinct().count() >= limit:
            raise serializers.ValidationError(
                {
                    _target_field(delivery): [
                        f"this target is already used by {limit} other accounts"
                    ]
                }
            )

    def create(self, validated: dict[str, Any]) -> Subscription:
        owner = self.context["request"].user
        limit = settings.MAX_SUBSCRIPTIONS_PER_USER
        with transaction.atomic():
            # Lock the owner, so parallel requests cannot all pass the count below.
            get_user_model().objects.select_for_update().filter(pk=owner.pk).first()
            if Subscription.objects.filter(owner=owner).count() >= limit:
                raise serializers.ValidationError(
                    f"at most {limit} subscriptions per user; delete one first"
                )
            delivery = validated.get("delivery", "")
            self._check_target(owner.pk, delivery, validated.get(_target_field(delivery)))
            validated["owner"] = owner
            instance = super().create(validated)
            self._ensure_secret(instance)
        return instance

    def update(self, instance: Subscription, validated: dict[str, Any]) -> Subscription:
        delivery = validated.get("delivery", instance.delivery)
        field = _target_field(delivery)
        target = validated.get(field, getattr(instance, field))
        current = getattr(instance, _target_field(instance.delivery))
        with transaction.atomic():
            if (delivery, target) != (instance.delivery, current):
                self._check_target(instance.owner_id, delivery, target)
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
        data.pop("webhook_secret", None)
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
