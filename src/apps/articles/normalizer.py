"""Normalization helpers for incoming feed entries.

- canonicalize_url: drop UTM query params, drop fragment, lower-case host.
- sanitize_html: bleach with conservative whitelist.
- content_hash: deterministic sha256.
- detect_language: langdetect with fixed seed; fallback 'simple'.
"""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import bleach
from langdetect import DetectorFactory, LangDetectException, detect

DetectorFactory.seed = 0

ALLOWED_TAGS = [
    "a", "p", "br", "strong", "em", "b", "i", "u", "ul", "ol", "li",
    "blockquote", "code", "pre", "h1", "h2", "h3", "h4", "h5", "h6",
    "img", "figure", "figcaption", "hr", "table", "thead", "tbody", "tr", "th", "td",
]
ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "rel"],
    "img": ["src", "alt", "title"],
}

_UTM_PREFIXES = ("utm_", "fbclid", "gclid", "yclid", "mc_", "ref")
_SUPPORTED_LANGS = {"ru": "russian", "en": "english"}


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    cleaned_query = [
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if not any(k.lower().startswith(p) for p in _UTM_PREFIXES)
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
    return bleach.clean(
        html or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        strip=True,
        strip_comments=True,
    )


def detect_language(text: str) -> str:
    snippet = (text or "").strip()
    if len(snippet) < 20:
        return "simple"
    try:
        code = detect(snippet[:4096])
    except LangDetectException:
        return "simple"
    return _SUPPORTED_LANGS.get(code, "simple")


def content_hash(canonical_url: str, title: str, body: str) -> str:
    payload = f"{canonical_url}\n{title.strip()}\n{(body or '').strip()[:512]}".encode()
    return hashlib.sha256(payload).hexdigest()
