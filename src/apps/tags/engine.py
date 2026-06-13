"""Tag rule matcher: applies active TagRules to a newly-created article."""

from __future__ import annotations

from apps.articles.models import Article
from apps.articles.normalizer import MAX_HTML_CHARS, plain_text
from apps.tags.models import ArticleTag, TagRule


def _haystack(article: Article) -> str:
    # Keywords match the visible text, not markup ("table" in <table>) or entities (&amp;).
    visible = (plain_text(html, MAX_HTML_CHARS) for html in (article.summary, article.body))
    return " ".join([article.title, *visible]).lower()


def apply_rules_to_article(article_id: int) -> list[int]:
    """Returns the list of tag ids that were assigned."""
    article = Article.objects.get(pk=article_id, is_deleted=False)
    text = _haystack(article)
    assigned: list[int] = []
    rules = TagRule.objects.filter(is_active=True).only(
        "id", "keywords", "match", "language", "tag_id"
    )
    for rule in rules:
        if rule.language and rule.language != article.language:
            continue
        kws = [k.lower() for k in rule.keywords if k]
        if not kws:
            continue
        hit_count = sum(1 for kw in kws if kw in text)
        matched = (rule.match == TagRule.Match.ANY and hit_count > 0) or (
            rule.match == TagRule.Match.ALL and hit_count == len(kws)
        )
        if matched:
            _, created = ArticleTag.objects.get_or_create(article_id=article_id, tag_id=rule.tag_id)
            if created:
                assigned.append(rule.tag_id)
    return assigned
