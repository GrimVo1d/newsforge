from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework import serializers

from apps.feeds.models import Feed
from apps.feeds.validators import SSRFError, assert_public_url

DUPLICATE_URL = "a feed with this url already exists"


class FeedSerializer(serializers.ModelSerializer[Feed]):
    """Full view for staff, including crawl state."""

    # Uniqueness is checked against live feeds only: a deleted feed's URL can be added again.
    url = serializers.CharField(max_length=2048)

    class Meta:
        model = Feed
        fields = (
            "id",
            "url",
            "site_url",
            "title",
            "language",
            "interval_seconds",
            "last_fetched_at",
            "next_fetch_at",
            "last_status",
            "consecutive_errors",
            "disabled_until",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "site_url",
            "title",
            "last_fetched_at",
            "next_fetch_at",
            "last_status",
            "consecutive_errors",
            "disabled_until",
            "created_at",
            "updated_at",
        )

    def validate_interval_seconds(self, value: int) -> int:
        if value < settings.MIN_FEED_INTERVAL_SECONDS:
            raise serializers.ValidationError(
                f"must be at least {settings.MIN_FEED_INTERVAL_SECONDS} seconds"
            )
        return value

    def validate_url(self, value: str) -> str:
        try:
            assert_public_url(value)
        except SSRFError as exc:
            raise serializers.ValidationError(str(exc), code="ssrf_blocked") from exc
        live = Feed.objects.filter(url=value, is_deleted=False)
        if self.instance is not None:
            live = live.exclude(pk=self.instance.pk)
        if live.exists():
            raise serializers.ValidationError(DUPLICATE_URL)
        return value

    def create(self, validated_data: dict[str, Any]) -> Feed:
        deleted = Feed.objects.filter(url=validated_data["url"], is_deleted=True).first()
        if deleted is not None:
            # Adding a deleted feed again restores it (with its articles) and starts afresh.
            for name, value in validated_data.items():
                setattr(deleted, name, value)
            deleted.is_deleted = False
            deleted.is_active = validated_data.get("is_active", True)
            deleted.reset_crawl_state()
            deleted.save()
            return deleted
        try:
            with transaction.atomic():
                return super().create(validated_data)
        except IntegrityError as exc:  # added concurrently
            raise serializers.ValidationError({"url": [DUPLICATE_URL]}) from exc

    def update(self, instance: Feed, validated_data: dict[str, Any]) -> Feed:
        if "url" in validated_data and validated_data["url"] != instance.url:
            instance.reset_crawl_state()
        try:
            with transaction.atomic():
                return super().update(instance, validated_data)
        except IntegrityError as exc:  # a deleted feed still holds that url
            raise serializers.ValidationError({"url": [DUPLICATE_URL]}) from exc


class PublicFeedSerializer(serializers.ModelSerializer[Feed]):
    """What non-staff users see: no crawl state."""

    class Meta:
        model = Feed
        fields = ("id", "url", "site_url", "title", "language", "created_at")
        read_only_fields = fields
