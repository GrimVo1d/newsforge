from __future__ import annotations

from rest_framework import serializers

from apps.feeds.models import Feed
from apps.feeds.validators import SSRFError, assert_public_url


class FeedSerializer(serializers.ModelSerializer):
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

    def validate_url(self, value: str) -> str:
        try:
            assert_public_url(value)
        except SSRFError as exc:
            raise serializers.ValidationError({"code": "ssrf_blocked", "detail": str(exc)}) from exc
        return value
