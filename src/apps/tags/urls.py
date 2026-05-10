from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.tags.views import ArticleTagView, TagViewSet

router = DefaultRouter()
router.register("tags", TagViewSet, basename="tag")

urlpatterns = [
    *router.urls,
    path("articles/<int:article_id>/tags/", ArticleTagView.as_view(), name="article-tags"),
]
