from __future__ import annotations

from rest_framework import serializers

from apps.articles.models import Article


class ArticleSerializer(serializers.ModelSerializer[Article]):
    feed_id = serializers.IntegerField(read_only=True)
    tags = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields: tuple[str, ...] = (
            "id",
            "feed_id",
            "title",
            "url",
            "summary",
            "author",
            "language",
            "published_at",
            "fetched_at",
            "tags",
        )
        read_only_fields = fields

    def get_tags(self, obj: Article) -> list[str]:
        return [link.tag.slug for link in obj.article_tags.all()]


class ArticleDetailSerializer(ArticleSerializer):
    class Meta(ArticleSerializer.Meta):
        fields = (*ArticleSerializer.Meta.fields, "body")
        read_only_fields = fields
