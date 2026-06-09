from django.urls import include, path
from rest_framework.routers import APIRootView

from apps.core.views import RegisterView, TokenRefreshThrottledView, TokenView

# App routers are SimpleRouters (no root view each); this one root lists every resource.
api_root = APIRootView.as_view(
    api_root_dict={
        "feeds": "feed-list",
        "articles": "article-list",
        "tags": "tag-list",
        "tag-rules": "tag-rule-list",
        "subscriptions": "subscription-list",
        "search": "search",
    }
)

urlpatterns = [
    path("", api_root, name="api-root"),
    path("auth/register/", RegisterView.as_view(), name="auth-register"),
    path("auth/token/", TokenView.as_view(), name="auth-token"),
    path("auth/token/refresh/", TokenRefreshThrottledView.as_view(), name="auth-token-refresh"),
    path("", include("apps.feeds.urls")),
    path("", include("apps.articles.urls")),
    path("", include("apps.tags.urls")),
    path("", include("apps.search.urls")),
    path("", include("apps.subscriptions.urls")),
]
