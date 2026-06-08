"""httpx.MockTransport that streams its responses like a real connection.

A response built with ``content=`` is read (and decoded) when it is created, but
``apps.core.safe_http`` reads raw, still-encoded bytes from a streamed response.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx


def streamed(response: httpx.Response) -> httpx.Response:
    if not response.is_stream_consumed:
        return response
    return httpx.Response(
        response.status_code, headers=response.headers, stream=httpx.ByteStream(response.content)
    )


def mock_transport(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: streamed(handler(request)))
