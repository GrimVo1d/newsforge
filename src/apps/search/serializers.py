from __future__ import annotations

import re
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

MAX_QUERY_CHARS = 256
MAX_OFFSET = 10_000
MAX_FEEDS = 50
_ID_RE = re.compile(r"^[1-9][0-9]{0,17}$")
LANG_CHOICES = ("russian", "english", "simple", "ru", "en")


@extend_schema_field(serializers.ListField(child=serializers.IntegerField(min_value=1)))
class FeedIdsField(serializers.Field[list[int], Any, Any, Any]):
    """``feed=1&feed=2`` or ``feed=1,2``; every item must be a positive integer."""

    def get_value(self, dictionary: Any) -> Any:
        if hasattr(dictionary, "getlist"):
            return dictionary.getlist(self.field_name) or serializers.empty
        return super().get_value(dictionary)

    def to_internal_value(self, data: Any) -> list[int]:
        items = data if isinstance(data, list) else [data]
        ids: list[int] = []
        for chunk in items:
            for part in str(chunk).split(","):
                part = part.strip()
                if not _ID_RE.match(part):
                    raise serializers.ValidationError(f"not a feed id: {part[:20]!r}")
                ids.append(int(part))
        if len(ids) > MAX_FEEDS:
            raise serializers.ValidationError(f"at most {MAX_FEEDS} feeds")
        return sorted(set(ids))

    def to_representation(self, value: list[int]) -> list[int]:
        return value


class SearchParamsSerializer(serializers.Serializer[Any]):
    q = serializers.CharField(
        max_length=MAX_QUERY_CHARS, required=False, default="", allow_blank=True
    )
    lang = serializers.ChoiceField(choices=LANG_CHOICES, required=False, allow_null=True)
    sort = serializers.ChoiceField(choices=("rank", "date"), default="rank")
    feed = FeedIdsField(required=False, default=list)
    # Sent as ?from= / ?to=; renamed by the view because "from" is a Python keyword.
    date_from = serializers.DateTimeField(required=False, allow_null=True)
    date_to = serializers.DateTimeField(required=False, allow_null=True)
    limit = serializers.IntegerField(min_value=1, max_value=100, default=20)
    offset = serializers.IntegerField(min_value=0, max_value=MAX_OFFSET, default=0)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        start, end = attrs.get("date_from"), attrs.get("date_to")
        if start and end and start >= end:
            raise serializers.ValidationError({"to": "must be later than from"})
        return attrs


class SearchHitSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField()
    title = serializers.CharField()
    summary = serializers.CharField()
    url = serializers.CharField()
    feed_id = serializers.IntegerField()
    published_at = serializers.DateTimeField(allow_null=True)
    language = serializers.CharField()
    rank = serializers.FloatField()
    highlight = serializers.CharField()


class SearchResponseSerializer(serializers.Serializer[Any]):
    count = serializers.IntegerField(help_text="Number of results on this page.")
    results = SearchHitSerializer(many=True)
