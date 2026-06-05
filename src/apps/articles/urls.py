from rest_framework.routers import DefaultRouter

from apps.articles.views import ArticleViewSet

router = DefaultRouter()
router.register("articles", ArticleViewSet, basename="article")
urlpatterns = router.urls
