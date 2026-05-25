"""HTTP fetcher for RSS/Atom feeds with ETag / If-Modified-Since and size cap."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from django.conf import settings

from apps.feeds.validators import SSRFError, assert_public_url


@dataclass(slots=True)
class FetchResult:
    status: str
    # one of: ok | not_modified | too_large | http_error | network_error | ssrf_blocked
    http_status: int | None
    body: bytes | None
    etag: str | None
    last_modified: str | None


def fetch(
    url: str,
    *,
    etag: str | None,
    last_modified: str | None,
) -> FetchResult:
    try:
        assert_public_url(url)
    except SSRFError:
        return FetchResult("ssrf_blocked", None, None, None, None)

    accept = "application/atom+xml, application/rss+xml, " "application/xml;q=0.9, */*;q=0.5"
    headers = {"User-Agent": settings.USER_AGENT, "Accept": accept}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    max_bytes = settings.MAX_RESPONSE_BYTES
    try:
        with httpx.Client(timeout=settings.HTTP_TIMEOUT, follow_redirects=True) as client:
            with client.stream("GET", url, headers=headers) as resp:
                if resp.status_code == 304:
                    return FetchResult("not_modified", 304, None, etag, last_modified)
                if resp.status_code >= 400:
                    return FetchResult("http_error", resp.status_code, None, None, None)
                buf = bytearray()
                for chunk in resp.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        return FetchResult("too_large", resp.status_code, None, None, None)
                return FetchResult(
                    "ok",
                    resp.status_code,
                    bytes(buf),
                    resp.headers.get("etag"),
                    resp.headers.get("last-modified"),
                )
    except httpx.HTTPError:
        return FetchResult("network_error", None, None, None, None)
