from __future__ import annotations

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.articles.models import Article
from apps.core.permissions import IsStaffOrReadOnly
from apps.tags.models import ArticleTag, Tag, TagRule
from apps.tags.serializers import (
    ArticleTagInputSerializer,
    ArticleTagSerializer,
    TagRuleSerializer,
    TagSerializer,
)


class TagViewSet(viewsets.ModelViewSet[Tag]):
    """Tags are shared: everyone reads them, staff manage them."""

    queryset = Tag.objects.all().order_by("slug")
    serializer_class = TagSerializer
    permission_classes = (IsStaffOrReadOnly,)


class TagRuleViewSet(viewsets.ModelViewSet[TagRule]):
    """Keyword rules that auto-tag new articles. They apply to every article, so staff only."""

    queryset = TagRule.objects.select_related("tag").order_by("id")
    serializer_class = TagRuleSerializer
    permission_classes = (permissions.IsAdminUser,)


class ArticleTagView(APIView):
    """Attach a tag to an article or detach it (staff only)."""

    permission_classes = (permissions.IsAdminUser,)

    @extend_schema(
        request=ArticleTagInputSerializer,
        responses={200: ArticleTagSerializer, 201: ArticleTagSerializer},
    )
    def post(self, request: Request, article_id: int) -> Response:
        article = get_object_or_404(Article, pk=article_id, is_deleted=False)
        s = ArticleTagInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        tag = get_object_or_404(Tag, pk=s.validated_data["tag_id"])
        _, created = ArticleTag.objects.get_or_create(article=article, tag=tag)
        return Response(
            {"article_id": article.id, "tag_id": tag.id},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(request=ArticleTagInputSerializer, responses={204: None})
    def delete(self, request: Request, article_id: int) -> Response:
        article = get_object_or_404(Article, pk=article_id, is_deleted=False)
        s = ArticleTagInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        ArticleTag.objects.filter(article=article, tag_id=s.validated_data["tag_id"]).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
