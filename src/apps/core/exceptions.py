"""Uniform error envelope: {"code": "<machine_code>", "detail": "<human>"}.

Wired in settings via REST_FRAMEWORK['EXCEPTION_HANDLER'].
"""

from __future__ import annotations

from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler


def envelope(exc, context) -> Response | None:  # type: ignore[no-untyped-def]
    response = exception_handler(exc, context)
    if response is None:
        return None
    data = response.data
    # Already in envelope shape (raised manually as {"code": ..., "detail": ...})
    if isinstance(data, dict) and "code" in data and "detail" in data:
        return response

    if isinstance(exc, exceptions.AuthenticationFailed):
        code = "authentication_failed"
    elif isinstance(exc, exceptions.NotAuthenticated):
        code = "not_authenticated"
    elif isinstance(exc, exceptions.PermissionDenied):
        code = "permission_denied"
    elif isinstance(exc, exceptions.NotFound):
        code = "not_found"
    elif isinstance(exc, exceptions.MethodNotAllowed):
        code = "method_not_allowed"
    elif isinstance(exc, exceptions.Throttled):
        code = "rate_limited"
    elif isinstance(exc, exceptions.ValidationError):
        code = "validation_error"
    else:
        code = "error"

    response.data = {"code": code, "detail": data}
    return response
