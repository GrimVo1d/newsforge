from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from apps.core.health import LiveView, ReadyView


class HealthCheckMiddleware:
    """Answer /health/live and /health/ready before host validation and the HTTPS redirect.

    Container and orchestrator probes connect by IP over plain http (``127.0.0.1:8000``),
    which ALLOWED_HOSTS would reject and SECURE_SSL_REDIRECT would redirect. The answers carry
    no data beyond up/down, so they are safe to give to any host.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self.views = {"/health/live": LiveView.as_view(), "/health/ready": ReadyView.as_view()}

    def __call__(self, request: HttpRequest) -> HttpResponse:
        view = self.views.get(request.path_info)
        if view is None:
            return self.get_response(request)
        response = view(request)
        response.render()  # a DRF Response; Django renders it only after the view middleware
        return response
