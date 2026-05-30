"""Polite robots.txt policy with 24h Redis cache."""

from __future__ import annotations

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from django.conf import settings
from django.core.cache import cache

from apps.core import safe_http

CACHE_TTL_SECONDS = 86_400
MAX_ROBOTS_BYTES = 200_000
DEFAULT_USER_AGENT = "newsforge"
DISALLOW_ALL = "User-agent: *\nDisallow: /\n"


def _cache_key(domain: str) -> str:
    return f"robots:{domain}"


def _fetch_robots(domain: str, scheme: str) -> str:
    url = f"{scheme}://{domain}/robots.txt"
    try:
        resp = safe_http.request(
            "GET",
            url,
            headers={"User-Agent": settings.USER_AGENT},
            timeout=5.0,
            max_bytes=MAX_ROBOTS_BYTES,
            allow_http=settings.ALLOW_PLAIN_HTTP,
            truncate=True,
        )
    except safe_http.UnsafeURLError:
        return DISALLOW_ALL
    except (safe_http.DeadlineExceededError, httpx.HTTPError):
        return ""  # unreachable: treat as allow-all, the feed fetch decides
    if resp.status_code >= 300:
        return ""  # no robots.txt (or a redirect loop): allow-all
    return resp.text


def is_allowed(url: str, user_agent: str = DEFAULT_USER_AGENT) -> bool:
    parsed = urlparse(url)
    if not parsed.hostname:
        return False
    domain = parsed.hostname.lower()
    scheme = parsed.scheme or "https"

    body = cache.get(_cache_key(domain))
    if body is None:
        body = _fetch_robots(domain, scheme)
        cache.set(_cache_key(domain), body, CACHE_TTL_SECONDS)
    if not body:
        return True

    parser = RobotFileParser()
    parser.parse(body.splitlines())
    return parser.can_fetch(user_agent, url)


def invalidate(domain: str) -> None:
    cache.delete(_cache_key(domain))
