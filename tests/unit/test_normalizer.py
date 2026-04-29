from apps.articles.normalizer import canonicalize_url, content_hash, sanitize_html


def test_canonicalize_drops_utm_and_fragment():
    a = canonicalize_url("https://Example.COM/path/?utm_source=x&b=2&a=1#frag")
    assert a == "https://example.com/path/?a=1&b=2"


def test_canonicalize_sorts_query_params():
    a = canonicalize_url("https://x.io/?z=1&a=2")
    b = canonicalize_url("https://x.io/?a=2&z=1")
    assert a == b


def test_canonicalize_strips_default_port():
    assert canonicalize_url("https://x.io:443/p") == "https://x.io/p"


def test_sanitize_html_drops_scripts():
    out = sanitize_html("<p>ok</p><script>alert(1)</script>")
    assert "<script>" not in out
    assert "<p>ok</p>" in out


def test_content_hash_stable():
    a = content_hash("https://x/p", "title", "body" * 100)
    b = content_hash("https://x/p", "title", "body" * 100)
    assert a == b and len(a) == 64
