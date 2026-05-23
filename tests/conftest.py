from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model


@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(username="alice", password="passpasspass")


@pytest.fixture
def feed(db):
    from apps.feeds.models import Feed

    return Feed.objects.create(url="https://example.com/feed.xml", language="english")
