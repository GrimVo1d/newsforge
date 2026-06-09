from rest_framework.routers import SimpleRouter

from apps.feeds.views import FeedViewSet

router = SimpleRouter()
router.register("feeds", FeedViewSet, basename="feed")

urlpatterns = router.urls
