"""Polite robots.txt policy (RFC 9309) with a Redis cache.

Outcomes of fetching ``/robots.txt`` (RFC 9309, 2.3.1):

- 2xx: parse it; cached for 24 h;
- 4xx (and too many redirects): no rules, everything allowed; cached for 24 h;
- 5xx or a network error: the site is "unreachable", everything disallowed; cached for
  ``RETRY_TTL_SECONDS`` only, so the feed is retried soon;
- a host that is not public: allowed here, so the feed fetch itself reports ``ssrf_blocked``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import quote, unquote, urlsplit

import httpx
from django.conf import settings
from django.core.cache import cache

from apps.core import safe_http

CACHE_TTL_SECONDS = 86_400
RETRY_TTL_SECONDS = 1_800
MAX_ROBOTS_BYTES = 500 * 1024  # RFC 9309 2.5: parse at least 500 KiB
DISALLOW_ALL = "User-agent: *\nDisallow: /\n"


def _cache_key(domain: str) -> str:
    return f"robots:{domain}"


def _fetch_robots(domain: str, scheme: str) -> tuple[str, int]:
    """Return the robots.txt policy text for a host and how long to cache it."""
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
        return "", RETRY_TTL_SECONDS  # the feed fetch reports ssrf_blocked
    except (safe_http.DeadlineExceededError, httpx.HTTPError):
        return DISALLOW_ALL, RETRY_TTL_SECONDS
    if resp.status_code >= 500:
        return DISALLOW_ALL, RETRY_TTL_SECONDS
    if resp.status_code >= 300:
        return "", CACHE_TTL_SECONDS  # no robots.txt (or a redirect loop): allow-all
    return resp.content.decode("utf-8", errors="replace"), CACHE_TTL_SECONDS


def product_token(user_agent: str | None = None) -> str:
    """The robots.txt product token of a User-Agent: ``newsforge/0.1 (...)`` → ``newsforge``."""
    token = re.match(r"[A-Za-z_-]*", user_agent or settings.USER_AGENT)
    return (token.group(0) if token else "").lower()


MAX_RULES = 2_000  # per robots.txt; more is not a policy, it is an attack on the parser
MAX_PATTERN_CHARS = 2_048


@dataclass(frozen=True, slots=True)
class _Rule:
    allow: bool
    pattern: str
    parts: tuple[str, ...]  # the pattern split on "*"
    anchored: bool  # ended with "$"

    def matches(self, path: str) -> bool:
        """Wildcard match in linear passes (no backtracking regex: patterns come from the host).

        The first part must be a prefix of the path, every next part is found left to right
        after the previous one; with "$" the last part must end the path.
        """
        first, *rest = self.parts
        if not path.startswith(first):
            return False
        if not rest:
            return not self.anchored or path == first
        pos = len(first)
        last = rest.pop() if self.anchored else None
        for part in rest:
            found = path.find(part, pos)
            if found < 0:
                return False
            pos = found + len(part)
        return last is None or (path.endswith(last) and len(path) - len(last) >= pos)


def _normalize_path(path: str) -> str:
    # Compare in one canonical percent-encoding; "/" and the reserved characters stay as is.
    return quote(unquote(path), safe="/?=&;:@!$'()*+,~-._%")


def _rule(allow: bool, pattern: str) -> _Rule:
    anchored = pattern.endswith("$")
    body = _normalize_path(pattern[:-1] if anchored else pattern)
    return _Rule(allow, pattern, tuple(body.split("*")), anchored)


def _agent_token(value: str) -> str:
    """``User-agent: newsforge/0.1`` names the product token ``newsforge``."""
    if value.strip() == "*":
        return "*"
    match = re.match(r"[A-Za-z_-]*", value.strip())
    return (match.group(0) if match else "").lower()


@lru_cache(maxsize=32)  # bodies are up to 500 KiB each
def _rules_for(body: str, token: str) -> tuple[_Rule, ...]:
    """Rules of all groups that name ``token``, else of the ``*`` groups (RFC 9309 2.2.1)."""
    groups: dict[str, list[_Rule]] = {}
    agents: list[str] = []
    in_rules = False
    count = 0
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if in_rules:
                agents, in_rules = [], False
            agents.append(_agent_token(value))
            groups.setdefault(agents[-1], [])  # a group exists even if all its rules are empty
        elif key in ("allow", "disallow") and agents:
            in_rules = True
            if not value or len(value) > MAX_PATTERN_CHARS or count >= MAX_RULES:
                continue  # an empty rule matches nothing
            count += 1
            rule = _rule(key == "allow", value)
            for agent in agents:
                groups[agent].append(rule)
    if token and token in groups:
        return tuple(groups[token])
    return tuple(groups.get("*", ()))


def can_fetch(body: str, url: str, token: str) -> bool:
    """Longest matching rule wins; on a tie ``Allow`` wins; no match means allowed."""
    parts = urlsplit(url)
    path = _normalize_path((parts.path or "/") + (f"?{parts.query}" if parts.query else ""))
    if path == "/robots.txt":
        return True
    best: _Rule | None = None
    for rule in _rules_for(body, token):
        if not rule.matches(path):
            continue
        if (
            best is None
            or len(rule.pattern) > len(best.pattern)
            or (len(rule.pattern) == len(best.pattern) and rule.allow)
        ):
            best = rule
    return best is None or best.allow


def is_allowed(url: str, user_agent: str | None = None) -> bool:
    parsed = urlsplit(url)
    if not parsed.hostname:
        return False
    domain = parsed.hostname.lower()
    scheme = parsed.scheme or "https"

    body = cache.get(_cache_key(domain))
    if body is None:
        body, ttl = _fetch_robots(domain, scheme)
        cache.set(_cache_key(domain), body, ttl)
    if not body:
        return True
    return can_fetch(body, url, product_token(user_agent))


def invalidate(domain: str) -> None:
    cache.delete(_cache_key(domain))
