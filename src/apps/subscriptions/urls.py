from rest_framework.routers import SimpleRouter

from apps.subscriptions.views import SubscriptionViewSet

router = SimpleRouter()
router.register("subscriptions", SubscriptionViewSet, basename="subscription")
urlpatterns = router.urls
