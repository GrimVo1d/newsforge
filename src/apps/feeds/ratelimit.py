"""Per-domain token-bucket rate limit for outbound fetches, backed by Redis.

Atomic via SET NX EX: a lock key with TTL = min interval. If SET NX succeeds,
the caller "got the token"; otherwise the domain is on cooldown.
"""

from __future__ import annotations

from urllib.parse import urlparse

import redis
from django.conf import settings

_pool: redis.ConnectionPool | None = None


def _client() -> redis.Redis:
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool.from_url(settings.CACHES["default"]["LOCATION"])
    return redis.Redis(connection_pool=_pool)


def _key(domain: str) -> str:
    return f"rl:fetch:{domain}"


def try_acquire(url: str, *, interval_seconds: int | None = None) -> bool:
    """Return True if the caller may fetch from this URL's domain right now."""
    domain = urlparse(url).hostname or ""
    if not domain:
        return False
    ttl = interval_seconds or settings.PER_DOMAIN_MIN_INTERVAL
    return bool(_client().set(_key(domain), b"1", nx=True, ex=ttl))


def reset(domain: str) -> None:
    _client().delete(_key(domain))
