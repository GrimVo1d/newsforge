from __future__ import annotations

import socket
from unittest.mock import patch

import httpx
import pytest

from apps.core import safe_http
from apps.core.safe_http import UnsafeURLError
from apps.feeds.validators import SSRFError, assert_public_url

PUBLIC = "93.184.216.34"
GETADDRINFO = "apps.core.safe_http.socket.getaddrinfo"


def _resolves_to(*ips: str):
    def fake(host, port, *args, **kwargs):
        return [
            (
                socket.AF_INET6 if ":" in ip else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (ip, port),
            )
            for ip in ips
        ]

    return patch(GETADDRINFO, side_effect=fake)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.5",
        "172.16.3.4",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
    ],
)
def test_rejects_non_public_addresses(ip):
    with _resolves_to(ip), pytest.raises(SSRFError):
        assert_public_url("https://feeds.example.internal/rss")


def test_rejects_when_any_address_is_private():
    with _resolves_to(PUBLIC, "10.0.0.1"), pytest.raises(SSRFError):
        assert_public_url("https://feeds.example.internal/rss")


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://feeds.example.internal/",
        "http://feeds.example.internal/feed",
        "https://feeds.example.internal:8443/feed",
        "https://user:pw@feeds.example.internal/feed",
        "https:///feed",
        "https://[::1/feed",
    ],
)
def test_rejects_bad_urls(url):
    with _resolves_to(PUBLIC), pytest.raises(SSRFError):
        assert_public_url(url)


def test_plain_http_is_opt_in():
    with _resolves_to(PUBLIC):
        assert_public_url("http://feeds.example.internal/feed", allow_http=True)


def test_dns_failure_is_rejected():
    with patch(GETADDRINFO, side_effect=socket.gaierror("nope")), pytest.raises(SSRFError):
        assert_public_url("https://missing.example.internal/feed")


def test_accepts_public_ip():
    with _resolves_to(PUBLIC):
        target = safe_http.resolve("https://feeds.example.internal/rss?x=1")
    assert target.pinned_url == f"https://{PUBLIC}:443/rss?x=1"
    assert target.host == "feeds.example.internal"


# --- request(): pinning, redirects, limits ---------------------------------


def _transport(handler):
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.MockTransport(wrapped), seen


def test_request_is_pinned_to_checked_address():
    transport, seen = _transport(lambda r: httpx.Response(200, content=b"ok"))
    with _resolves_to(PUBLIC):
        resp = safe_http.request("GET", "https://feeds.example.internal/rss", transport=transport)
    assert resp.content == b"ok"
    (req,) = seen
    assert req.url.host == PUBLIC
    assert req.headers["host"] == "feeds.example.internal"
    assert req.extensions["sni_hostname"] == "feeds.example.internal"


def test_redirect_targets_are_checked_on_every_hop():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://internal.example.internal/"})

    transport, _ = _transport(handler)

    def fake(host, port, *args, **kwargs):
        ip = "10.0.0.1" if host.startswith("internal") else PUBLIC
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    with patch(GETADDRINFO, side_effect=fake), pytest.raises(UnsafeURLError):
        safe_http.request("GET", "https://feeds.example.internal/rss", transport=transport)


def test_redirects_are_followed_and_capped():
    def handler(request: httpx.Request) -> httpx.Response:
        n = int(request.url.path.strip("/") or 0)
        return httpx.Response(301, headers={"location": f"/{n + 1}"})

    transport, seen = _transport(handler)
    with _resolves_to(PUBLIC):
        resp = safe_http.request(
            "GET", "https://feeds.example.internal/", transport=transport, max_redirects=3
        )
    assert resp.status_code == 301
    assert len(seen) == 4
    assert resp.url == "https://feeds.example.internal/3"


def test_https_to_http_redirect_is_refused():
    transport, _ = _transport(
        lambda r: httpx.Response(302, headers={"location": "http://feeds.example.internal/"})
    )
    with _resolves_to(PUBLIC), pytest.raises(UnsafeURLError):
        safe_http.request("GET", "https://feeds.example.internal/", transport=transport)


def test_body_size_is_capped():
    transport, _ = _transport(lambda r: httpx.Response(200, content=b"x" * 2048))
    with _resolves_to(PUBLIC):
        with pytest.raises(safe_http.ResponseTooLargeError):
            safe_http.request(
                "GET", "https://feeds.example.internal/", transport=transport, max_bytes=1024
            )
        resp = safe_http.request(
            "GET",
            "https://feeds.example.internal/",
            transport=transport,
            max_bytes=1024,
            truncate=True,
        )
    assert resp.truncated
    assert len(resp.content) == 1024


def test_proxy_environment_is_ignored(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.internal:3128")
    transport, seen = _transport(lambda r: httpx.Response(200))
    with _resolves_to(PUBLIC):
        safe_http.request("GET", "https://feeds.example.internal/", transport=transport)
    assert seen[0].url.host == PUBLIC
