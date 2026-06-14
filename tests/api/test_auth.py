from __future__ import annotations

from datetime import timedelta

import pytest
from django.conf import settings
from rest_framework.throttling import ScopedRateThrottle

pytestmark = pytest.mark.django_db

REGISTER = "/api/v1/auth/register/"
TOKEN = "/api/v1/auth/token/"


def test_register_and_obtain_token(api):
    resp = api.post(REGISTER, {"username": "bob", "password": "correct-horse-battery"})
    assert resp.status_code == 201
    assert resp.json()["username"] == "bob"

    resp = api.post(TOKEN, {"username": "bob", "password": "correct-horse-battery"})
    assert resp.status_code == 200
    assert {"access", "refresh"} <= resp.json().keys()


def test_register_duplicate_username_is_conflict(api, user):
    resp = api.post(REGISTER, {"username": user.username, "password": "correct-horse-battery"})
    assert resp.status_code == 409
    assert resp.json()["code"] == "username_taken"


@pytest.mark.parametrize("password", ["short", "password123", "12345678901"])
def test_register_rejects_weak_passwords(api, password):
    resp = api.post(REGISTER, {"username": "carol", "password": password})
    assert resp.status_code == 400
    assert resp.json()["code"] == "validation_error"


def test_register_rejects_invalid_username(api):
    resp = api.post(REGISTER, {"username": "bad name!", "password": "correct-horse-battery"})
    assert resp.status_code == 400


def test_auth_endpoints_are_throttled(api, monkeypatch):
    from django.core.cache import cache

    cache.clear()
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {"auth": "2/min"})
    codes = [api.post(TOKEN, {"username": "x", "password": "y"}).status_code for _ in range(3)]
    assert codes == [401, 401, 429]
    cache.clear()


def test_registrations_per_address_are_capped_per_day(api, user, monkeypatch):
    from django.core.cache import cache

    from apps.core.views import RegisterThrottle

    cache.clear()
    monkeypatch.setattr(RegisterThrottle, "THROTTLE_RATES", {"register": "2/day"})
    api.force_authenticate(user)  # signing in does not lift the cap
    codes = [
        api.post(REGISTER, {"username": f"new{n}", "password": "pw-Long-enough-42"}).status_code
        for n in range(3)
    ]
    assert codes == [201, 201, 429]
    assert RegisterThrottle().parse_rate("20/day") == (20, 86400)
    cache.clear()


def test_jwt_lifetimes_are_applied():
    from rest_framework_simplejwt.settings import api_settings

    expected = {"access": timedelta(minutes=15), "refresh": timedelta(days=7)}
    actual = {
        "access": api_settings.ACCESS_TOKEN_LIFETIME,
        "refresh": api_settings.REFRESH_TOKEN_LIFETIME,
    }
    assert actual == expected
    assert settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"] == expected["access"]


def test_production_password_hashers_are_installed():
    # Tests run with a fast MD5 hasher; make sure the real ones can load their libraries.
    from django.utils.module_loading import import_string

    from newsforge.settings import base

    for path in base.PASSWORD_HASHERS:
        hasher = import_string(path)()
        assert hasher.verify("pw", hasher.encode("pw", hasher.salt()))
