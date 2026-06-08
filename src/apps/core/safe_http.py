"""Outbound HTTP for user-supplied URLs (feeds, robots.txt, webhooks).

Every hop of a request goes through the same checks, which closes the usual SSRF gaps of
"validate the URL, then hand it to an HTTP client":

- only http(s) on the default ports 80/443;
- the host is resolved once and *every* address must be globally routable;
- the connection is pinned to the checked address (no second DNS lookup, so no rebinding),
  while ``Host`` and TLS SNI / certificate verification still use the original hostname;
- redirects are followed manually and each target is checked again;
- an overall deadline covers all hops and the body download;
- the body is read in chunks and capped *after* decompression (gzip bombs stop at the cap).
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import time
import zlib
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

ALLOWED_PORTS = {"http": 80, "https": 443}
REDIRECT_CODES = {301, 302, 303, 307, 308}
# The body is decoded here, so only advertise what _read_body can decode with a size limit.
ACCEPT_ENCODING = "gzip, deflate"
# Shown to API users instead of the resolved address, so errors do not map internal DNS.
NOT_PUBLIC = "host does not resolve to a public address"

logger = logging.getLogger(__name__)

# IPv6 ranges whose last 32 bits are an IPv4 address the packet may end up at. Python's
# is_global treats some of them as global (e.g. NAT64 64:ff9b::/96), so the embedded address
# is checked instead.
_EMBEDS_IPV4 = (
    ipaddress.IPv6Network("::/96"),  # IPv4-compatible (deprecated)
    ipaddress.IPv6Network("::ffff:0:0/96"),  # IPv4-mapped
    ipaddress.IPv6Network("::ffff:0:0:0/96"),  # IPv4-translated
    ipaddress.IPv6Network("64:ff9b::/96"),  # NAT64 well-known prefix
)
_NEVER_PUBLIC = (
    ipaddress.IPv6Network("64:ff9b:1::/48"),  # NAT64 local use
    ipaddress.IPv6Network("fec0::/10"),  # site-local (deprecated)
)


class UnsafeURLError(ValueError):
    """The URL (or a redirect target) must not be fetched from the server."""


class ResponseTooLargeError(Exception):
    pass


class DeadlineExceededError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Target:
    scheme: str
    host: str
    port: int
    address: IPAddress
    path: str  # path + query, never empty

    @property
    def pinned_url(self) -> str:
        literal = f"[{self.address}]" if self.address.version == 6 else str(self.address)
        return f"{self.scheme}://{literal}:{self.port}{self.path}"


@dataclass(frozen=True, slots=True)
class Response:
    status_code: int
    headers: httpx.Headers
    content: bytes
    url: str
    truncated: bool = False

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


def _is_public(ip: IPAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        if any(ip in net for net in _NEVER_PUBLIC):
            return False
        if any(ip in net for net in _EMBEDS_IPV4):
            return _is_public(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
        if ip.sixtofour is not None:
            return _is_public(ip.sixtofour)
    return ip.is_global and not ip.is_multicast


def resolve(url: str, *, allow_http: bool = False) -> Target:
    """Check a URL and resolve its host; raise UnsafeURLError when it is not public."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UnsafeURLError(f"malformed url: {exc}") from exc

    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_PORTS:
        raise UnsafeURLError(f"scheme not allowed: {scheme!r}")
    if scheme == "http" and not allow_http:
        raise UnsafeURLError("plain http is not allowed; use https")
    default_port = ALLOWED_PORTS[scheme]
    if port not in (None, default_port):
        raise UnsafeURLError(f"port not allowed: {port}")
    if parts.username or parts.password:
        raise UnsafeURLError("credentials in url are not allowed")
    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise UnsafeURLError("missing host")

    try:
        infos = socket.getaddrinfo(host, default_port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        logger.info("dns resolution failed for %r: %s", host, exc)
        raise UnsafeURLError(NOT_PUBLIC) from exc

    addresses: list[IPAddress] = []
    for *_, sockaddr in infos:
        ip = ipaddress.ip_address(str(sockaddr[0]).split("%", 1)[0])
        if not _is_public(ip):
            logger.info("%r resolves to non-public address %s", host, ip)
            raise UnsafeURLError(NOT_PUBLIC)
        addresses.append(ip)
    if not addresses:
        raise UnsafeURLError(NOT_PUBLIC)

    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    return Target(scheme, host, default_port, addresses[0], path)


def request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
    timeout: float = 20.0,
    max_bytes: int = 5 * 1024 * 1024,
    max_redirects: int = 5,
    allow_http: bool = False,
    truncate: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> Response:
    """Send a request to a public URL.

    Raises UnsafeURLError, ResponseTooLargeError (unless ``truncate``), DeadlineExceededError,
    or httpx.HTTPError for transport failures. Redirects beyond ``max_redirects`` are returned
    as-is (a 3xx response).
    """
    deadline = time.monotonic() + timeout
    method = method.upper()

    with httpx.Client(transport=transport, trust_env=False, follow_redirects=False) as client:
        for hop in range(max_redirects + 1):
            target = resolve(url, allow_http=allow_http)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DeadlineExceededError(url)
            host_header = target.host if ":" not in target.host else f"[{target.host}]"
            req = client.build_request(
                method,
                target.pinned_url,
                headers={
                    **(headers or {}),
                    "Host": host_header,
                    "Accept-Encoding": ACCEPT_ENCODING,
                },
                content=content,
                timeout=remaining,
                extensions={"sni_hostname": target.host} if target.scheme == "https" else None,
            )
            resp = client.send(req, stream=True)
            try:
                location = resp.headers.get("location")
                if resp.status_code in REDIRECT_CODES and location and hop < max_redirects:
                    url = urljoin(url, location)
                    if resp.status_code == 303 or (
                        resp.status_code in (301, 302) and method == "POST"
                    ):
                        method, content = "GET", None
                    continue
                body, truncated = _read_body(resp, max_bytes, deadline, truncate)
                return Response(resp.status_code, resp.headers, body, url, truncated)
            finally:
                resp.close()
    raise AssertionError("unreachable")  # pragma: no cover


def _decompressor(resp: httpx.Response, first: bytes) -> zlib._Decompress | None:
    encoding = resp.headers.get("content-encoding", "").strip().lower()
    if encoding in ("", "identity"):
        return None
    if encoding in ("gzip", "x-gzip"):
        return zlib.decompressobj(16 + zlib.MAX_WBITS)
    if encoding == "deflate":
        # "deflate" is meant to be zlib-wrapped, but some servers send a raw stream.
        wrapped = len(first) >= 2 and first[0] & 0x0F == 8 and (first[0] << 8 | first[1]) % 31 == 0
        return zlib.decompressobj(zlib.MAX_WBITS if wrapped else -zlib.MAX_WBITS)
    raise httpx.DecodingError(f"unsupported content-encoding: {encoding}", request=resp.request)


def _read_body(
    resp: httpx.Response, max_bytes: int, deadline: float, truncate: bool
) -> tuple[bytes, bool]:
    declared = resp.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes and not truncate:
        raise ResponseTooLargeError(declared)
    buf = bytearray()
    limit = max_bytes + 1  # one byte over the cap is enough to know it is too large
    decoder: zlib._Decompress | None = None
    started = False
    try:
        for chunk in resp.iter_raw():
            if time.monotonic() > deadline:
                raise DeadlineExceededError(str(resp.request.url))
            if not started:
                decoder, started = _decompressor(resp, chunk), True
            if decoder is None:
                buf.extend(chunk)
            else:
                # Decompress at most up to the cap; the rest of a bomb is never expanded.
                data = chunk
                while data and len(buf) < limit:
                    buf.extend(decoder.decompress(data, limit - len(buf)))
                    data = decoder.unconsumed_tail
            if len(buf) > max_bytes:
                break
        if decoder is not None and len(buf) <= max_bytes:
            buf.extend(decoder.flush())
    except zlib.error as exc:
        raise httpx.DecodingError(f"invalid compressed body: {exc}", request=resp.request) from exc
    if len(buf) > max_bytes:
        if truncate:
            return bytes(buf[:max_bytes]), True
        raise ResponseTooLargeError(len(buf))
    return bytes(buf), False
