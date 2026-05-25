from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.articles.models import Article
from apps.tags.models import ArticleTag, Tag
from apps.tags.serializers import TagSerializer


class TagViewSet(viewsets.ModelViewSet):
    queryset = Tag.objects.all().order_by("slug")
    serializer_class = TagSerializer
    permission_classes = (permissions.IsAuthenticatedOrReadOnly,)


class _ArticleTagInputSerializer(serializers.Serializer):
    tag_id = serializers.IntegerField()


class ArticleTagView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request: Request, article_id: int) -> Response:
        article = get_object_or_404(Article, pk=article_id, is_deleted=False)
        s = _ArticleTagInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        tag = get_object_or_404(Tag, pk=s.validated_data["tag_id"])
        ArticleTag.objects.get_or_create(article=article, tag=tag)
        return Response(
            {"article_id": article.id, "tag_id": tag.id},
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request: Request, article_id: int) -> Response:
        article = get_object_or_404(Article, pk=article_id, is_deleted=False)
        s = _ArticleTagInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        ArticleTag.objects.filter(article=article, tag_id=s.validated_data["tag_id"]).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
