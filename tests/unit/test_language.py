from apps.articles.normalizer import detect_language


def test_detect_english():
    assert detect_language("The quick brown fox jumps over the lazy dog repeatedly today") == "english"


def test_detect_russian():
    assert detect_language("Российская федерация объявляет о новых возможностях в области технологий") == "russian"


def test_detect_short_falls_back_to_simple():
    assert detect_language("hi") == "simple"


def test_detect_empty():
    assert detect_language("") == "simple"
