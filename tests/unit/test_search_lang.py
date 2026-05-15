from apps.search.queries import coerce_lang


def test_default_is_simple():
    assert coerce_lang(None) == "simple"
    assert coerce_lang("") == "simple"


def test_accepts_supported():
    assert coerce_lang("russian") == "russian"
    assert coerce_lang("english") == "english"


def test_aliases():
    assert coerce_lang("ru") == "russian"
    assert coerce_lang("en") == "english"


def test_unknown_falls_back():
    assert coerce_lang("klingon") == "simple"
    assert coerce_lang("'; DROP TABLE x;--") == "simple"
