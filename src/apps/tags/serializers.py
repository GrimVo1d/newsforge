from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.feeds.models import Language
from apps.tags.models import Tag, TagRule

MAX_KEYWORDS = 50


class TagSerializer(serializers.ModelSerializer[Tag]):
    slug = serializers.SlugField(max_length=64)

    class Meta:
        model = Tag
        fields = ("id", "name", "slug", "is_auto")
        read_only_fields = ("is_auto",)

    def validate_slug(self, value: str) -> str:
        qs = Tag.objects.filter(slug=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("tag with this slug already exists")
        return value


class TagRuleSerializer(serializers.ModelSerializer[TagRule]):
    keywords = serializers.ListField(
        child=serializers.CharField(max_length=64, trim_whitespace=True),
        allow_empty=False,
        max_length=MAX_KEYWORDS,
    )
    language = serializers.ChoiceField(choices=Language.choices, required=False, allow_null=True)
    tag = serializers.PrimaryKeyRelatedField(queryset=Tag.objects.all())

    class Meta:
        model = TagRule
        fields = ("id", "name", "keywords", "match", "language", "tag", "is_active", "owner")
        read_only_fields = ("owner",)

    def create(self, validated: dict[str, Any]) -> TagRule:
        validated["owner"] = self.context["request"].user
        return super().create(validated)


class ArticleTagInputSerializer(serializers.Serializer[Any]):
    tag_id = serializers.IntegerField(min_value=1)


class ArticleTagSerializer(serializers.Serializer[Any]):
    article_id = serializers.IntegerField()
    tag_id = serializers.IntegerField()
