from django.urls import include, path

from apps.core.views import RegisterView, TokenRefreshThrottledView, TokenView

urlpatterns = [
    path("auth/register/", RegisterView.as_view(), name="auth-register"),
    path("auth/token/", TokenView.as_view(), name="auth-token"),
    path("auth/token/refresh/", TokenRefreshThrottledView.as_view(), name="auth-token-refresh"),
    path("", include("apps.feeds.urls")),
    path("", include("apps.tags.urls")),
    path("", include("apps.search.urls")),
    path("", include("apps.subscriptions.urls")),
]
