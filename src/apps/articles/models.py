from __future__ import annotations

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models


class Article(models.Model):
    feed = models.ForeignKey(
        "feeds.Feed", on_delete=models.CASCADE, related_name="articles", db_column="feed_id"
    )
    guid = models.TextField(blank=True, default="")
    canonical_url = models.TextField()
    url = models.TextField()
    title = models.TextField()
    summary = models.TextField(blank=True, default="")
    body = models.TextField(blank=True, default="")
    author = models.TextField(null=True, blank=True)
    language = models.CharField(max_length=8, default="simple")
    content_hash = models.CharField(max_length=64)
    published_at = models.DateTimeField(null=True, blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    tsv = SearchVectorField(null=True, editable=False)

    class Meta:
        db_table = "articles_article"
        indexes = [
            models.Index(fields=["feed", "-published_at"], name="articles_feed_pub_idx"),
            models.Index(fields=["-published_at"], name="articles_pub_idx"),
            GinIndex(fields=["tsv"], name="articles_tsv_idx", condition=models.Q(is_deleted=False)),
        ]

    def __str__(self) -> str:
        return self.title[:80]
