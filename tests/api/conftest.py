from __future__ import annotations

import pytest
from rest_framework.test import APIClient


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.fixture
def user_api(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def staff(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        username="staff", password="staff-pass-123", is_staff=True
    )


@pytest.fixture
def staff_api(staff) -> APIClient:
    client = APIClient()
    client.force_authenticate(staff)
    return client
