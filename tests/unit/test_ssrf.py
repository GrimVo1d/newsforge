from __future__ import annotations

import gzip
import socket
import zlib
from unittest.mock import patch

import httpx
import pytest

from apps.core import safe_http
from apps.core.safe_http import UnsafeURLError
from apps.feeds.validators import SSRFError, assert_public_url
from tests.httpmock import mock_transport

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
        # IPv6 forms that embed a private IPv4 address
        "64:ff9b::a00:5",
        "64:ff9b::a9fe:a9fe",
        "64:ff9b:1::5db8:d822",
        "::7f00:1",
        "::ffff:0:7f00:1",
        "2002:a00:1::1",
        "fec0::1",
        "5f00::1",
        "192.88.99.1",
        "2002:c058:6301::1",  # 6to4 of the relay anycast address
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


def test_nat64_of_a_public_address_is_allowed():
    with _resolves_to("64:ff9b::5db8:d822"):  # 93.184.216.34
        assert_public_url("https://feeds.example.internal/rss")


def test_error_does_not_reveal_the_resolved_address():
    with _resolves_to("10.0.0.5"), pytest.raises(SSRFError) as exc:
        assert_public_url("https://db/")
    assert "10.0.0.5" not in str(exc.value)
    with patch(GETADDRINFO, side_effect=socket.gaierror("nope")), pytest.raises(SSRFError) as dns:
        assert_public_url("https://missing.example.internal/feed")
    assert str(dns.value) == str(exc.value)


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

    return mock_transport(wrapped), seen


def test_request_is_pinned_to_checked_address():
    transport, seen = _transport(lambda r: httpx.Response(200, content=b"ok"))
    with _resolves_to(PUBLIC):
        resp = safe_http.request("GET", "https://feeds.example.internal/rss", transport=transport)
    assert resp.content == b"ok"
    (req,) = seen
    assert req.url.host == PUBLIC
    assert req.headers["host"] == "feeds.example.internal"
    assert req.extensions["sni_hostname"] == "feeds.example.internal"


def test_idn_host_is_sent_as_an_a_label():
    transport, seen = _transport(lambda r: httpx.Response(200, content=b"ok"))
    with _resolves_to(PUBLIC) as dns:
        safe_http.request("GET", "https://Bücher.example.internal/rss", transport=transport)
    assert dns.call_args.args[0] == "xn--bcher-kva.example.internal"
    (req,) = seen
    assert req.headers["host"] == "xn--bcher-kva.example.internal"
    assert req.extensions["sni_hostname"] == "xn--bcher-kva.example.internal"


def test_invalid_idn_host_is_unsafe():
    with pytest.raises(UnsafeURLError):
        safe_http.resolve("https://☃..example.internal/rss")


@pytest.mark.parametrize(
    "url, canonical",
    [
        (
            "HTTPS://WWW.Example.Internal:443/rss?b=2&a=1#top",
            "https://www.example.internal/rss?b=2&a=1",
        ),
        ("https://example.internal", "https://example.internal/"),
        ("https://Bücher.Example.Internal./Feed", "https://xn--bcher-kva.example.internal/Feed"),
        ("http://example.internal:80/a", "http://example.internal/a"),
        ("https://example.internal:8443/a", "https://example.internal:8443/a"),
        ("https://[2001:DB8::1]:443/a", "https://[2001:db8::1]/a"),
    ],
)
def test_canonical_url(url, canonical):
    assert safe_http.canonical_url(url) == canonical


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


def _encoded(body: bytes, encoding: str) -> httpx.Response:
    if encoding == "gzip":
        data = gzip.compress(body)
    elif encoding == "deflate":
        data = zlib.compress(body)
    else:  # raw deflate stream, sent by some servers as "deflate"
        c = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        data, encoding = c.compress(body) + c.flush(), "deflate"
    return httpx.Response(
        200, headers={"content-encoding": encoding}, stream=httpx.ByteStream(data)
    )


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "raw-deflate"])
def test_compressed_bodies_are_decoded(encoding):
    transport, seen = _transport(lambda r: _encoded(b"<rss/>" * 100, encoding))
    with _resolves_to(PUBLIC):
        resp = safe_http.request("GET", "https://feeds.example.internal/", transport=transport)
    assert resp.content == b"<rss/>" * 100
    assert seen[0].headers["accept-encoding"] == "gzip, deflate"


def test_decompression_stops_at_the_cap():
    bomb = gzip.compress(b"\0" * 20_000_000)  # ~20 KB on the wire
    transport, _ = _transport(
        lambda r: httpx.Response(
            200, headers={"content-encoding": "gzip"}, stream=httpx.ByteStream(bomb)
        )
    )
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


@pytest.mark.parametrize(
    ("encoding", "content"), [("gzip", b"not gzip at all"), ("br", b"\x0b\x02\x80")]
)
def test_undecodable_bodies_are_transport_errors(encoding, content):
    transport, _ = _transport(
        lambda r: httpx.Response(
            200, headers={"content-encoding": encoding}, stream=httpx.ByteStream(content)
        )
    )
    with _resolves_to(PUBLIC), pytest.raises(httpx.DecodingError):
        safe_http.request("GET", "https://feeds.example.internal/", transport=transport)


def test_data_after_the_compressed_stream_is_not_read():
    trailer_chunks = 0

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            nonlocal trailer_chunks
            yield gzip.compress(b"<rss/>")
            while True:  # an endless trailer after the end of the gzip member
                trailer_chunks += 1
                yield b"\0" * 4096

    transport, _ = _transport(
        lambda r: httpx.Response(200, headers={"content-encoding": "gzip"}, stream=Stream())
    )
    with _resolves_to(PUBLIC):
        resp = safe_http.request("GET", "https://feeds.example.internal/", transport=transport)
    assert resp.content == b"<rss/>"
    assert trailer_chunks <= 1


def test_raw_bytes_are_capped_even_when_they_decode_to_nothing():
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            while True:  # empty stored deflate blocks: raw bytes, no output, no end of stream
                yield b"\x00\x00\x00\xff\xff" * 1000

    transport, _ = _transport(
        lambda r: httpx.Response(200, headers={"content-encoding": "deflate"}, stream=Stream())
    )
    with _resolves_to(PUBLIC), pytest.raises(safe_http.ResponseTooLargeError):
        safe_http.request(
            "GET", "https://feeds.example.internal/", transport=transport, max_bytes=1024
        )


def test_discard_body_skips_reading():
    transport, _ = _transport(
        lambda r: httpx.Response(
            200, headers={"content-encoding": "gzip"}, stream=httpx.ByteStream(b"not gzip")
        )
    )
    with _resolves_to(PUBLIC):
        resp = safe_http.request(
            "POST", "https://hooks.example.internal/", transport=transport, discard_body=True
        )
    assert (resp.status_code, resp.content) == (200, b"")


@pytest.mark.parametrize(
    ("codes", "permanent"), [((301, 308), True), ((301, 302), False), ((), False)]
)
def test_permanent_url_only_after_permanent_redirects(codes, permanent):
    def handler(request: httpx.Request) -> httpx.Response:
        n = int(request.url.path.strip("/") or 0)
        if n < len(codes):
            return httpx.Response(codes[n], headers={"location": f"/{n + 1}"})
        return httpx.Response(200)

    transport, _ = _transport(handler)
    with _resolves_to(PUBLIC):
        resp = safe_http.request("GET", "https://feeds.example.internal/", transport=transport)
    expected = f"https://feeds.example.internal/{len(codes)}" if permanent else None
    assert resp.permanent_url == expected


def test_every_hop_gets_its_own_connection():
    clients: list[object] = []
    real = httpx.Client

    def tracking(*args, **kwargs):
        client = real(*args, **kwargs)
        clients.append(client)
        return client

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "a.example.internal":
            return httpx.Response(302, headers={"location": "https://b.example.internal/"})
        return httpx.Response(200)

    transport, seen = _transport(handler)
    with _resolves_to(PUBLIC), patch("apps.core.safe_http.httpx.Client", side_effect=tracking):
        safe_http.request("GET", "https://a.example.internal/", transport=transport)
    assert len(seen) == 2
    assert len(clients) == 2
