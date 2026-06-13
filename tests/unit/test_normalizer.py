import pytest

from apps.articles.normalizer import (
    InvalidEntryError,
    canonicalize_url,
    content_hash,
    normalize_entry,
    plain_text,
    sanitize_html,
)


def test_canonicalize_drops_utm_and_fragment():
    a = canonicalize_url("https://Example.INTERNAL/path/?utm_source=x&b=2&a=1#frag")
    assert a == "https://example.internal/path/?a=1&b=2"


def test_canonicalize_sorts_query_params():
    a = canonicalize_url("https://x.internal/?z=1&a=2")
    b = canonicalize_url("https://x.internal/?a=2&z=1")
    assert a == b


def test_canonicalize_strips_default_port():
    assert canonicalize_url("https://x.internal:443/p") == "https://x.internal/p"


def test_sanitize_html_drops_scripts():
    out = sanitize_html("<p>ok</p><script>alert(1)</script>")
    assert "<script>" not in out
    assert "<p>ok</p>" in out


def test_content_hash_stable():
    a = content_hash("https://x/p", "title", "body" * 100)
    b = content_hash("https://x/p", "title", "body" * 100)
    assert a == b and len(a) == 64


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Tom &amp; Jerry", "Tom & Jerry"),
        ("<b>Bold</b> move", "Bold move"),
        ("Line\r\nBreak\t here", "Line Break here"),
        ("&lt;script&gt;alert(1)&lt;/script&gt;", "<script>alert(1)</script>"),
        ("<script>alert(1)</script>Title", "alert(1)Title"),
        (None, ""),
    ],
)
def test_plain_text(raw, expected):
    assert plain_text(raw, 100) == expected


def test_plain_text_is_truncated():
    assert plain_text("x" * 50, 10) == "x" * 10


def test_entry_title_and_author_are_plain_text():
    entry = normalize_entry(
        url="https://example.internal/a",
        title="Q&amp;A: <i>Django</i>",
        summary="<p>ok</p>",
        body="",
        author="<a href='x'>Ann</a>",
    )
    assert entry.title == "Q&A: Django"
    assert entry.author == "Ann"


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "data:text/html,hi", "ftp://example.internal/x", "/relative", ""],
)
def test_entry_link_must_be_http(url):
    with pytest.raises(InvalidEntryError):
        normalize_entry(url=url, title="t", summary="", body="")


def test_tracking_params_are_matched_exactly():
    url = "https://example.internal/a?ref=rss&reference=1&refresh=2&mc_cid=x&mc_list=y"
    assert canonicalize_url(url) == "https://example.internal/a?mc_list=y&reference=1&refresh=2"


def test_bad_port_is_an_invalid_entry():
    with pytest.raises(InvalidEntryError):
        normalize_entry(url="https://example.internal:99999/a", title="t", summary="", body="")


def test_language_is_detected_on_visible_text():
    summary = (
        '<p><img src="https://cdn.example.com/images/2026/release-announcement-banner.png"'
        ' alt="release banner"><a href="https://github.com/example/project/releases/tag/'
        'v2.0.0-final">Читать далее о новой версии проекта</a></p>'
    )
    entry = normalize_entry(
        url="https://example.internal/l", title="Вышел релиз", summary=summary, body=""
    )
    assert entry.language == "russian"


def test_fallback_language_is_whitelisted():
    entry = normalize_entry(
        url="https://example.internal/l",
        title="x",
        summary="",
        body="",
        fallback_language="pg_catalog.english",
    )
    assert entry.language == "simple"


def test_html_is_capped_before_sanitizing():
    from apps.articles.normalizer import MAX_HTML_CHARS

    entry = normalize_entry(
        url="https://example.internal/l", title="t", summary="", body="<p>" + "a" * 300_000
    )
    assert len(entry.body) <= MAX_HTML_CHARS + len("</p>")
    assert entry.body.endswith("</p>")
