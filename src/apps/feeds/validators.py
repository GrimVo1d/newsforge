"""SSRF-safe URL validation for incoming feed URLs.

Reject:
- schemes other than http/https
- hosts that resolve to private / loopback / link-local / multicast / reserved IPs
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class SSRFError(ValueError):
    pass


_FORBIDDEN_PROPS = ("is_private", "is_loopback", "is_link_local", "is_multicast", "is_reserved")


def _is_forbidden(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(getattr(ip, p) for p in _FORBIDDEN_PROPS) or ip.is_unspecified


def assert_public_url(url: str, *, allow_http: bool = False) -> None:
    """Raise SSRFError when the URL is not safe to fetch from a server."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"scheme not allowed: {parsed.scheme!r}")
    if parsed.scheme == "http" and not allow_http:
        raise SSRFError("plain http is not allowed; use https")
    host = parsed.hostname
    if not host:
        raise SSRFError("missing host")

    try:
        infos = socket.getaddrinfo(host, parsed.port or 80, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SSRFError(f"dns resolution failed: {exc}") from exc

    for family, _, _, _, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise SSRFError(f"unparseable address: {ip_str}") from exc
        if _is_forbidden(ip):
            raise SSRFError(f"address {ip} is not publicly routable")
        _ = family  # not used
