"""HTTP fetcher for RSS/Atom feeds with ETag / If-Modified-Since and size cap."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from django.conf import settings

from apps.core import safe_http

ACCEPT = "application/atom+xml, application/rss+xml, application/xml;q=0.9, */*;q=0.5"


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
    transport: httpx.BaseTransport | None = None,
) -> FetchResult:
    headers = {"User-Agent": settings.USER_AGENT, "Accept": ACCEPT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    try:
        resp = safe_http.request(
            "GET",
            url,
            headers=headers,
            timeout=settings.HTTP_TIMEOUT,
            max_bytes=settings.MAX_RESPONSE_BYTES,
            allow_http=settings.ALLOW_PLAIN_HTTP,
            transport=transport,
        )
    except safe_http.UnsafeURLError:
        return FetchResult("ssrf_blocked", None, None, None, None)
    except safe_http.ResponseTooLargeError:
        return FetchResult("too_large", None, None, None, None)
    except (safe_http.DeadlineExceededError, httpx.HTTPError):
        return FetchResult("network_error", None, None, None, None)

    if resp.status_code == 304:
        return FetchResult("not_modified", 304, None, etag, last_modified)
    if resp.status_code >= 300:
        return FetchResult("http_error", resp.status_code, None, None, None)
    return FetchResult(
        "ok",
        resp.status_code,
        resp.content,
        resp.headers.get("etag"),
        resp.headers.get("last-modified"),
    )
