from __future__ import annotations

import django_filters
from django.db.models import F, Prefetch, QuerySet
from rest_framework import permissions, serializers, viewsets

from apps.articles.models import Article
from apps.articles.serializers import ArticleDetailSerializer, ArticleSerializer
from apps.search.queries import LANG_ALIASES
from apps.tags.models import ArticleTag


class ArticleFilter(django_filters.FilterSet):
    feed = django_filters.NumberFilter(field_name="feed_id")
    language = django_filters.CharFilter(method="filter_language")
    tag = django_filters.CharFilter(field_name="article_tags__tag__slug")
    published_after = django_filters.IsoDateTimeFilter(field_name="published_at", lookup_expr="gte")
    published_before = django_filters.IsoDateTimeFilter(field_name="published_at", lookup_expr="lt")

    class Meta:
        model = Article
        fields = ("feed", "language", "tag", "published_after", "published_before")

    def filter_language(
        self, queryset: QuerySet[Article], name: str, value: str
    ) -> QuerySet[Article]:
        value = value.lower()
        return queryset.filter(language=LANG_ALIASES.get(value, value))


class ArticleViewSet(viewsets.ReadOnlyModelViewSet[Article]):
    """Newest articles first; full-text search lives at /search/."""

    permission_classes = (permissions.AllowAny,)
    filterset_class = ArticleFilter

    def get_queryset(self) -> QuerySet[Article]:
        tags = Prefetch("article_tags", queryset=ArticleTag.objects.select_related("tag"))
        return (
            Article.objects.filter(is_deleted=False, feed__is_deleted=False)
            .prefetch_related(tags)
            .order_by(F("published_at").desc(nulls_last=True), "-id")
            .distinct()
        )

    def get_serializer_class(self) -> type[serializers.BaseSerializer[Article]]:
        return ArticleDetailSerializer if self.action == "retrieve" else ArticleSerializer
