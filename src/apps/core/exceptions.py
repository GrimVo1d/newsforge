"""Uniform error envelope: {"code": "<machine_code>", "detail": ...}.

``detail`` is a string, except for ``validation_error``, where it maps field names to lists
of messages (errors not tied to one field are under ``non_field_errors``).

Wired in settings via REST_FRAMEWORK['EXCEPTION_HANDLER']; ``handler404`` / ``handler500``
answer in the same shape for requests that never reach a DRF view.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404, HttpRequest, JsonResponse
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import exception_handler
from rest_framework_simplejwt.exceptions import InvalidToken

# Codes kept stable for clients, where DRF's own default_code differs.
_CODES: tuple[tuple[type[exceptions.APIException], str], ...] = (
    (InvalidToken, "token_not_valid"),
    (exceptions.Throttled, "rate_limited"),
    (exceptions.ValidationError, "validation_error"),
)


def _code(exc: exceptions.APIException) -> str:
    for cls, code in _CODES:
        if isinstance(exc, cls):
            return code
    return str(exc.default_code)


def _detail(exc: exceptions.APIException, data: Any) -> Any:
    if isinstance(exc, exceptions.ValidationError):
        if isinstance(data, dict):
            return data
        return {api_settings.NON_FIELD_ERRORS_KEY: data if isinstance(data, list) else [data]}
    if isinstance(data, dict) and "detail" in data:
        return str(data["detail"])
    return str(data)


def envelope(exc: Exception, context: dict[str, Any]) -> Response | None:
    # DRF maps these itself, but the original exception would not carry a code.
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()

    response = exception_handler(exc, context)
    if response is None or not isinstance(exc, exceptions.APIException):
        return response
    data = response.data
    # Raised by our views in envelope shape already, e.g. {"code": "username_taken", ...}.
    if isinstance(data, dict) and set(data) == {"code", "detail"}:
        return response
    response.data = {"code": _code(exc), "detail": _detail(exc, data)}
    return response


def not_found(request: HttpRequest, exception: Exception | None = None) -> JsonResponse:
    return JsonResponse({"code": "not_found", "detail": "Not found."}, status=404)


def server_error(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"code": "server_error", "detail": "Internal server error."}, status=500)
