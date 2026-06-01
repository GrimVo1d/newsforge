from __future__ import annotations

from django.conf import settings
from rest_framework import serializers

from apps.feeds.models import Feed
from apps.feeds.validators import SSRFError, assert_public_url


class FeedSerializer(serializers.ModelSerializer[Feed]):
    """Full view for staff, including crawl state."""

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
            raise serializers.ValidationError({"code": "ssrf_blocked", "detail": str(exc)}) from exc
        return value


class PublicFeedSerializer(serializers.ModelSerializer[Feed]):
    """What non-staff users see: no crawl state."""

    class Meta:
        model = Feed
        fields = ("id", "url", "site_url", "title", "language", "created_at")
        read_only_fields = fields
