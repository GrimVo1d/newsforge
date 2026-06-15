from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.core.health import LiveView, ReadyView, metrics_view

urlpatterns = [
    path("api/v1/", include("apps.core.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/schema/swagger-ui/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path("health/live", LiveView.as_view(), name="health-live"),
    path("health/ready", ReadyView.as_view(), name="health-ready"),
    path("metrics", metrics_view, name="metrics"),
]

# Errors outside DRF views (unknown paths, crashes) answer in the API's error envelope too.
handler404 = "apps.core.exceptions.not_found"
handler500 = "apps.core.exceptions.server_error"
