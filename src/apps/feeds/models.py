from __future__ import annotations

from django.db import models
from django.utils import timezone


class Language(models.TextChoices):
    RUSSIAN = "russian", "russian"
    ENGLISH = "english", "english"
    SIMPLE = "simple", "simple"


class FeedStatus(models.TextChoices):
    OK = "ok", "ok"
    NOT_MODIFIED = "not_modified", "not_modified"
    HTTP_ERROR = "http_error", "http_error"
    NETWORK_ERROR = "network_error", "network_error"
    PARSE_ERROR = "parse_error", "parse_error"
    ROBOTS_BLOCKED = "robots_blocked", "robots_blocked"
    TOO_LARGE = "too_large", "too_large"


class Feed(models.Model):
    url = models.TextField(unique=True)
    site_url = models.TextField(blank=True, default="")
    title = models.TextField(blank=True, default="")
    language = models.CharField(max_length=8, choices=Language.choices, default=Language.SIMPLE)
    etag = models.TextField(null=True, blank=True)
    last_modified = models.TextField(null=True, blank=True)
    interval_seconds = models.PositiveIntegerField(default=1800)
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    next_fetch_at = models.DateTimeField(default=timezone.now)
    last_status = models.CharField(max_length=32, blank=True, default="")
    consecutive_errors = models.PositiveIntegerField(default=0)
    disabled_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "feeds_feed"
        indexes = [
            models.Index(fields=["next_fetch_at"], name="feeds_due_basic_idx"),
            models.Index(
                fields=["disabled_until"],
                name="feeds_disabled_idx",
                condition=models.Q(disabled_until__isnull=False),
            ),
        ]

    def __str__(self) -> str:
        return self.url
