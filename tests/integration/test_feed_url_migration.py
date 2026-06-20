from __future__ import annotations

from importlib import import_module

import pytest
from django.apps import apps

from apps.feeds.models import Feed

pytestmark = pytest.mark.django_db

migration = import_module("apps.feeds.migrations.0004_canonical_feed_urls")


def test_existing_feed_urls_are_made_canonical():
    plain = Feed.objects.create(url="HTTPS://Blog.Example.Internal:443/rss#top")
    idn = Feed.objects.create(url="https://Bücher.example.internal/feed")
    canonical = Feed.objects.create(url="https://dup.example.internal/rss")
    clash = Feed.objects.create(url="https://DUP.example.internal/rss")
    migration._forwards(apps, None)
    urls = dict(Feed.objects.values_list("id", "url"))
    assert urls[plain.id] == "https://blog.example.internal/rss"
    assert urls[idn.id] == "https://xn--bcher-kva.example.internal/feed"
    assert urls[canonical.id] == "https://dup.example.internal/rss"
    assert urls[clash.id] == "https://DUP.example.internal/rss"  # left for the operator
