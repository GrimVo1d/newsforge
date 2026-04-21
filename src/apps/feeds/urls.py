from rest_framework.routers import DefaultRouter

from apps.feeds.views import FeedViewSet

router = DefaultRouter()
router.register("feeds", FeedViewSet, basename="feed")

urlpatterns = router.urls
