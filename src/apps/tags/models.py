from __future__ import annotations

from django.db import models


class Tag(models.Model):
    name = models.CharField(max_length=64, unique=True)
    slug = models.CharField(max_length=64, unique=True)
    is_auto = models.BooleanField(default=False)

    class Meta:
        db_table = "tags_tag"

    def __str__(self) -> str:
        return self.slug


class ArticleTag(models.Model):
    article = models.ForeignKey(
        "articles.Article",
        on_delete=models.CASCADE,
        related_name="article_tags",
        db_column="article_id",
    )
    tag = models.ForeignKey(
        Tag, on_delete=models.CASCADE, related_name="article_tags", db_column="tag_id"
    )

    class Meta:
        db_table = "tags_articletag"
        constraints = [
            models.UniqueConstraint(
                fields=["article", "tag"], name="tags_articletag_unique"
            ),
        ]
