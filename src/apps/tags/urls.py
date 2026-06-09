from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.tags.views import ArticleTagView, TagRuleViewSet, TagViewSet

router = SimpleRouter()
router.register("tags", TagViewSet, basename="tag")
router.register("tag-rules", TagRuleViewSet, basename="tag-rule")

urlpatterns = [
    *router.urls,
    path("articles/<int:article_id>/tags/", ArticleTagView.as_view(), name="article-tags"),
]
