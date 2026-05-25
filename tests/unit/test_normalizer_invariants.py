"""Hypothesis property tests for URL canonicalization and content_hash stability."""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.articles.normalizer import canonicalize_url, content_hash

_QUERY_KEYS = st.text(
    alphabet=st.characters(min_codepoint=ord("a"), max_codepoint=ord("z")),
    min_size=1,
    max_size=8,
)
_QUERY_VALS = st.text(min_size=0, max_size=8)


def _build(query: list[tuple[str, str]]) -> str:
    from urllib.parse import urlencode

    return f"https://example.com/path?{urlencode(query)}"


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(pairs=st.lists(st.tuples(_QUERY_KEYS, _QUERY_VALS), max_size=10))
def test_canonicalize_is_order_independent(pairs):
    a = canonicalize_url(_build(pairs))
    b = canonicalize_url(_build(list(reversed(pairs))))
    assert a == b


@settings(max_examples=100)
@given(
    title=st.text(min_size=1, max_size=120),
    body=st.text(min_size=0, max_size=400),
)
def test_content_hash_is_stable(title, body):
    h1 = content_hash("https://x/p", title, body)
    h2 = content_hash("https://x/p", title, body)
    assert h1 == h2
    assert len(h1) == 64


@settings(max_examples=100)
@given(prefix=st.text(min_size=0, max_size=20))
def test_canonicalize_strips_utm_no_matter_position(prefix):
    base = canonicalize_url("https://x.io/path?a=1")
    with_utm = canonicalize_url(f"https://x.io/path?{prefix}utm_source=z&a=1")
    # utm_-prefixed keys are dropped; non-utm keys preserved.
    assert "utm_source" not in with_utm
    assert "a=1" in with_utm
    assert "a=1" in base
