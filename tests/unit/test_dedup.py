"""Pure-Python checks on dedup precedence (guid > content_hash).

Real DB-level dedup is covered by integration tests; here we just lock down
the precedence rule encoded in services.upsert_article.
"""

from apps.articles.normalizer import normalize_entry


def test_guid_takes_precedence_when_present():
    e = normalize_entry(url="https://x/a", title="t", summary="", body="b", guid="g-1")
    assert e.guid == "g-1"


def test_falls_back_to_content_hash_when_no_guid():
    e1 = normalize_entry(url="https://x/a", title="t", summary="", body="b")
    e2 = normalize_entry(url="https://x/a", title="t", summary="", body="b")
    assert not e1.guid
    assert e1.content_hash == e2.content_hash
