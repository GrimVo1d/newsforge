from apps.search.queries import coerce_lang


def test_default_is_every_language():
    assert coerce_lang(None) is None
    assert coerce_lang("") is None


def test_every_language_is_tried_without_lang():
    from apps.search.queries import SEARCH_DATE_SQL, SEARCH_RANK_SQL, SUPPORTED_LANGS

    for sql in (SEARCH_RANK_SQL, SEARCH_DATE_SQL):
        for lang in SUPPORTED_LANGS:
            assert f"websearch_to_tsquery('{lang}'" in sql


def test_accepts_supported():
    assert coerce_lang("russian") == "russian"
    assert coerce_lang("english") == "english"


def test_aliases():
    assert coerce_lang("ru") == "russian"
    assert coerce_lang("en") == "english"


def test_unknown_falls_back():
    assert coerce_lang("klingon") == "simple"
    assert coerce_lang("'; DROP TABLE x;--") == "simple"
