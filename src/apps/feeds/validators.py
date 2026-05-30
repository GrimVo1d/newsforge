"""Validation of user-supplied URLs before they are stored.

The same checks run again on every outbound request (see ``apps.core.safe_http``), so a
host that later starts resolving to a private address is still refused at fetch time.
"""

from __future__ import annotations

from django.conf import settings

from apps.core.safe_http import UnsafeURLError, resolve

SSRFError = UnsafeURLError


def assert_public_url(url: str, *, allow_http: bool | None = None) -> None:
    """Raise SSRFError when the URL is not safe to fetch from a server."""
    if allow_http is None:
        allow_http = settings.ALLOW_PLAIN_HTTP
    resolve(url, allow_http=allow_http)
