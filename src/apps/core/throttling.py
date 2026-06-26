"""DRF throttles that key IPv6 clients by their /64 network.

A host usually gets a whole /64, so keying by the full address would let one client rotate
through 2**64 buckets. IPv4 (and IPv4-mapped IPv6) addresses are keyed as they are.
"""

from __future__ import annotations

import ipaddress

from rest_framework import throttling
from rest_framework.request import Request

IPV6_PREFIX = 64


def network_ident(ident: str) -> str:
    try:
        addr = ipaddress.ip_address(ident.strip())
    except ValueError:
        return ident
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return str(addr.ipv4_mapped)
        return str(ipaddress.IPv6Network((addr, IPV6_PREFIX), strict=False))
    return str(addr)


class AnonRateThrottle(throttling.AnonRateThrottle):
    def get_ident(self, request: Request) -> str:
        return network_ident(super().get_ident(request))


class UserRateThrottle(throttling.UserRateThrottle):
    def get_ident(self, request: Request) -> str:
        return network_ident(super().get_ident(request))


class ScopedRateThrottle(throttling.ScopedRateThrottle):
    def get_ident(self, request: Request) -> str:
        return network_ident(super().get_ident(request))


class RegisterThrottle(throttling.SimpleRateThrottle):
    """Accounts created per client address, whether or not the request is authenticated."""

    scope = "register"

    def get_ident(self, request: Request) -> str:
        return network_ident(super().get_ident(request))

    def get_cache_key(self, request: Request, view: object) -> str:
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
