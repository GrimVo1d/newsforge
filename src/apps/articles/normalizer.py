"""Normalization helpers for incoming feed entries.

- canonicalize_url: drop tracking query params, drop fragment, lower-case host.
- plain_text: titles and authors are stored as text, without markup or entities.
- sanitize_html: bleach with conservative whitelist (summary / body), input capped in size.
- content_hash: deterministic sha256 over the canonical URL, title and full text.
- detect_language: langdetect with fixed seed on plain text; fallback 'simple'.
"""

from __future__ import annotations

import hashlib
import html
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import bleach
from langdetect import DetectorFactory, LangDetectException, detect

DetectorFactory.seed = 0

ALLOWED_TAGS = [
    "a",
    "p",
    "br",
    "strong",
    "em",
    "b",
    "i",
    "u",
    "ul",
    "ol",
    "li",
    "blockquote",
    "code",
    "pre",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "img",
    "figure",
    "figcaption",
    "hr",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
]
ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "rel"],
    "img": ["src", "alt", "title"],
}

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_PARAMS = {"fbclid", "gclid", "yclid", "mc_cid", "mc_eid", "ref"}
_SUPPORTED_LANGS = {"ru": "russian", "en": "english"}

MAX_URL_CHARS = 2048
MAX_TITLE_CHARS = 1000
MAX_AUTHOR_CHARS = 255
# Summary and body HTML is cut to this many characters before sanitizing; the full-text index
# of one row is limited to 1 MB.
MAX_HTML_CHARS = 200_000
# Longer guids are stored as their sha256, so the unique index stays within its row limit.
MAX_GUID_CHARS = 512


class InvalidEntryError(ValueError):
    """The feed entry cannot be stored (e.g. its link is not an http(s) URL)."""


def _no_nul(value: str | None) -> str:
    # PostgreSQL text cannot hold NUL.
    return (value or "").replace("\x00", "")


def plain_text(value: str | None, max_chars: int) -> str:
    """Strip tags, decode entities and collapse whitespace."""
    text: str = bleach.clean(value or "", tags=[], strip=True, strip_comments=True)
    return " ".join(html.unescape(text).split())[:max_chars]


def check_link(url: str) -> str:
    url = _no_nul(url).strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise InvalidEntryError(f"not an http(s) link: {url[:100]!r}")
    try:
        parsed.port  # noqa: B018 - raises ValueError for a malformed port
    except ValueError as exc:
        raise InvalidEntryError(f"bad port in link: {url[:100]!r}") from exc
    if len(url) > MAX_URL_CHARS:
        raise InvalidEntryError("link too long")
    return url


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    cleaned_query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if k.lower() not in _TRACKING_PARAMS
        and not any(k.lower().startswith(p) for p in _TRACKING_PREFIXES)
    ]
    cleaned_query.sort()
    host = (parsed.hostname or "").lower()
    netloc = host
    if parsed.port and not (
        (parsed.scheme == "http" and parsed.port == 80)
        or (parsed.scheme == "https" and parsed.port == 443)
    ):
        netloc = f"{host}:{parsed.port}"
    path = parsed.path or "/"
    return urlunparse((parsed.scheme.lower(), netloc, path, "", urlencode(cleaned_query), ""))


def sanitize_html(html: str) -> str:
    cleaned: str = bleach.clean(
        _no_nul(html)[:MAX_HTML_CHARS],
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        strip=True,
        strip_comments=True,
    )
    return cleaned


def detect_language(text: str) -> str:
    snippet = (text or "").strip()
    if len(snippet) < 20:
        return "simple"
    try:
        code = detect(snippet[:4096])
    except LangDetectException:
        return "simple"
    return _SUPPORTED_LANGS.get(str(code), "simple")


def content_hash(canonical_url: str, title: str, body: str) -> str:
    # Migration articles.0006 computes the same value in SQL; keep them in step.
    payload = f"{canonical_url}\n{title.strip()}\n{(body or '').strip()}".encode()
    return hashlib.sha256(payload).hexdigest()


def normalize_guid(guid: str | None) -> str:
    guid = _no_nul(guid).strip()
    if len(guid) > MAX_GUID_CHARS:
        return "sha256:" + hashlib.sha256(guid.encode()).hexdigest()
    return guid


@dataclass(slots=True)
class NormalizedEntry:
    """Result of normalize_entry: ready-for-upsert fields."""

    canonical_url: str
    url: str
    title: str
    summary: str
    body: str
    author: str | None
    language: str
    content_hash: str
    guid: str
    published_at: datetime | None


def normalize_entry(
    *,
    url: str,
    title: str,
    summary: str,
    body: str,
    guid: str = "",
    author: str | None = None,
    published_at: datetime | None = None,
    fallback_language: str = "simple",
) -> NormalizedEntry:
    """Raises InvalidEntryError for entries that must be skipped.

    ``fallback_language`` (the feed's language) is used when the text is too short or too
    ambiguous for detection.
    """
    url = check_link(url)
    canonical = canonicalize_url(url)
    clean_title = plain_text(_no_nul(title), MAX_TITLE_CHARS)
    clean_summary = sanitize_html(summary)
    clean_body = sanitize_html(body)
    visible = (plain_text(html, MAX_HTML_CHARS) for html in (clean_summary, clean_body))
    lang = detect_language(" ".join([clean_title, *visible]))
    if lang == "simple" and fallback_language in _SUPPORTED_LANGS.values():
        lang = fallback_language
    digest = content_hash(canonical, clean_title, clean_body or clean_summary)
    if published_at is not None:
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=UTC)
        published_at = min(published_at, datetime.now(UTC))  # no articles from the future
    return NormalizedEntry(
        canonical_url=canonical,
        url=url,
        title=clean_title,
        summary=clean_summary,
        body=clean_body,
        author=plain_text(_no_nul(author), MAX_AUTHOR_CHARS) or None,
        language=lang,
        content_hash=digest,
        guid=normalize_guid(guid),
        published_at=published_at,
    )
