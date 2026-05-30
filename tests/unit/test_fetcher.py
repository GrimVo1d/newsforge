from __future__ import annotations

import socket
from unittest.mock import patch

import httpx
import pytest

from apps.feeds.fetcher import fetch


@pytest.fixture(autouse=True)
def public_dns():
    def fake(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    with patch("apps.core.safe_http.socket.getaddrinfo", side_effect=fake):
        yield


URL = "https://feeds.example.internal/rss"


def _fetch(handler, **kwargs):
    return fetch(
        URL, etag=kwargs.get("etag"), last_modified=None, transport=httpx.MockTransport(handler)
    )


def test_ok_returns_body_and_validators():
    resp = httpx.Response(200, content=b"<rss/>", headers={"etag": '"abc"'})
    result = _fetch(lambda r: resp)
    assert (result.status, result.body, result.etag) == ("ok", b"<rss/>", '"abc"')


def test_conditional_headers_and_304():
    def handler(request):
        assert request.headers["if-none-match"] == '"abc"'
        return httpx.Response(304)

    assert _fetch(handler, etag='"abc"').status == "not_modified"


def test_http_error_and_too_large(settings):
    assert _fetch(lambda r: httpx.Response(503)).status == "http_error"
    settings.MAX_RESPONSE_BYTES = 10
    assert _fetch(lambda r: httpx.Response(200, content=b"x" * 11)).status == "too_large"


def test_network_error():
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    assert _fetch(handler).status == "network_error"


def test_private_target_is_blocked():
    with patch(
        "apps.core.safe_http.socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 443))],
    ):
        assert _fetch(lambda r: httpx.Response(200)).status == "ssrf_blocked"
