"""Polite robots.txt policy with 24h Redis cache."""

from __future__ import annotations

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from django.conf import settings
from django.core.cache import cache

CACHE_TTL_SECONDS = 86_400
DEFAULT_USER_AGENT = "newsforge"


def _cache_key(domain: str) -> str:
    return f"robots:{domain}"


def _fetch_robots(domain: str, scheme: str) -> str:
    url = f"{scheme}://{domain}/robots.txt"
    try:
        with httpx.Client(timeout=5.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": settings.USER_AGENT})
        if resp.status_code >= 400:
            return ""  # treat as allow-all
        return resp.text[:200_000]
    except httpx.HTTPError:
        return ""


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
