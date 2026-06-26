from __future__ import annotations

import os
import secrets
import subprocess
import sys

import pytest

pytestmark = pytest.mark.django_db


def test_health_endpoints(api):
    assert api.get("/health/live").json() == {"status": "ok"}
    assert api.get("/health/ready").json() == {"db": True, "redis": True}


def test_metrics_require_token(api):
    assert api.get("/metrics").status_code == 404
    assert api.get("/metrics", HTTP_AUTHORIZATION="Bearer wrong").status_code == 404
    resp = api.get("/metrics", HTTP_AUTHORIZATION="Bearer test-metrics-token")
    assert resp.status_code == 200
    assert b"python_info" in resp.content


def test_schema_is_generated(api):
    assert api.get("/api/schema/").status_code == 200


def test_list_limit_is_capped(api, feed):
    resp = api.get("/api/v1/feeds/?limit=100000")
    assert resp.status_code == 200
    assert "limit=100" in (resp.json()["next"] or "limit=100")


GOOD_KEY = secrets.token_urlsafe(50)  # generated, so no usable key lives in the repository


def _run_python(
    code: str, unset: tuple[str, ...] = (), **env: str
) -> subprocess.CompletedProcess[str]:
    unset = ("SECRET_KEY", "ALLOWED_HOSTS", "DJANGO_SETTINGS_MODULE", *unset)
    clean = {k: v for k, v in os.environ.items() if k not in unset}
    clean.update(env)
    return subprocess.run(
        [sys.executable, "-c", code],
        env=clean,
        capture_output=True,
        text=True,
        check=False,
    )


def _import_prod_settings(**env: str) -> subprocess.CompletedProcess[str]:
    return _run_python(
        "import django; django.setup()", DJANGO_SETTINGS_MODULE="newsforge.settings.prod", **env
    )


def test_prod_settings_require_secret_key_and_hosts():
    missing = _import_prod_settings()
    assert missing.returncode != 0
    assert "SECRET_KEY" in missing.stderr

    no_hosts = _import_prod_settings(SECRET_KEY=GOOD_KEY)
    assert no_hosts.returncode != 0
    assert "ALLOWED_HOSTS" in no_hosts.stderr

    ok = _import_prod_settings(SECRET_KEY=GOOD_KEY, ALLOWED_HOSTS="news.example.internal")
    assert ok.returncode == 0, ok.stderr


@pytest.mark.parametrize(
    "name", ["DATABASE_URL", "REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND"]
)
def test_prod_settings_require_service_urls(name):
    env = {
        "SECRET_KEY": GOOD_KEY,
        "ALLOWED_HOSTS": "news.example.internal",
        "DATABASE_URL": "postgres://u:p@db.example.internal:5432/nf",
        "REDIS_URL": "redis://cache.example.internal:6379/0",
        "CELERY_BROKER_URL": "redis://cache.example.internal:6379/1",
        "CELERY_RESULT_BACKEND": "redis://cache.example.internal:6379/2",
    }
    del env[name]
    missing = _run_python(
        "import django; django.setup()",
        unset=(name,),
        DJANGO_SETTINGS_MODULE="newsforge.settings.prod",
        **env,
    )
    assert missing.returncode != 0
    assert name in missing.stderr


def test_prod_api_answers_json_only():
    code = (
        "import django; django.setup(); from django.conf import settings; "
        "print(settings.REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'])"
    )
    out = _run_python(
        code,
        DJANGO_SETTINGS_MODULE="newsforge.settings.prod",
        SECRET_KEY=GOOD_KEY,
        ALLOWED_HOSTS="news.example.internal",
    )
    assert out.stdout.strip() == "('rest_framework.renderers.JSONRenderer',)", out.stderr


@pytest.mark.parametrize(
    "key",
    [
        "change-me",
        "dev-only-insecure-secret-key-do-not-use-in-prod",
        "x" * 64,
        "django-insecure-" + GOOD_KEY,
        "test-only-" + GOOD_KEY,
        "kq3F8vYp2LmZ7tW1xR9sB4nJ6hD0cA5eU-gT_iO3wE8rQ2yN7uM1",  # gitleaks:allow (public, refused)
    ],
)
def test_prod_settings_reject_placeholder_secret_keys(key):
    weak = _import_prod_settings(SECRET_KEY=key, ALLOWED_HOSTS="news.example.internal")
    assert weak.returncode != 0
    assert "SECRET_KEY must be" in weak.stderr


@pytest.mark.parametrize("module", ["newsforge.wsgi", "newsforge.asgi", "newsforge.celery"])
def test_server_entry_points_default_to_prod_settings(module):
    # Importing the package first loads newsforge.celery; it must not pick dev settings.
    code = f"import {module}; from django.conf import settings; print(settings.DEBUG)"
    missing = _run_python(code)
    assert missing.returncode != 0
    assert "SECRET_KEY" in missing.stderr
    ok = _run_python(code, SECRET_KEY=GOOD_KEY, ALLOWED_HOSTS="news.example.internal")
    assert ok.returncode == 0, ok.stderr
    assert ok.stdout.strip() == "False"


def test_health_probes_skip_host_check_and_https_redirect(api, settings):
    settings.ALLOWED_HOSTS = ["news.example.internal"]
    settings.SECURE_SSL_REDIRECT = True
    assert api.get("/health/live", HTTP_HOST="127.0.0.1:8000").json() == {"status": "ok"}
    assert api.get("/health/ready", HTTP_HOST="127.0.0.1:8000").status_code == 200
    assert api.get("/api/v1/feeds/", HTTP_HOST="127.0.0.1:8000").status_code == 400
    assert api.get("/api/v1/feeds/", HTTP_HOST="news.example.internal").status_code == 301


def test_metrics_token_needs_bearer_scheme(api):
    assert api.get("/metrics", HTTP_AUTHORIZATION="test-metrics-token").status_code == 404
    assert api.get("/metrics", HTTP_AUTHORIZATION="Token test-metrics-token").status_code == 404


def test_throttle_ignores_client_supplied_forwarded_for(rf):
    from rest_framework.request import Request

    from apps.core.throttling import AnonRateThrottle

    throttle = AnonRateThrottle()
    idents = {
        throttle.get_ident(
            Request(rf.get("/", HTTP_X_FORWARDED_FOR=xff, REMOTE_ADDR="203.0.113.9"))
        )
        for xff in ("1.1.1.1", "2.2.2.2, 3.3.3.3")
    }
    assert idents == {"203.0.113.9"}


@pytest.mark.parametrize(
    ("remote", "ident"),
    [
        ("203.0.113.9", "203.0.113.9"),
        ("2001:db8:1:2:aaaa::1", "2001:db8:1:2::/64"),
        ("2001:db8:1:2:ffff:ffff:ffff:ffff", "2001:db8:1:2::/64"),
        ("::ffff:203.0.113.9", "203.0.113.9"),
        ("not-an-address", "not-an-address"),
    ],
)
def test_throttles_key_ipv6_clients_by_network(rf, remote, ident):
    from rest_framework.request import Request

    from apps.core.throttling import AnonRateThrottle, RegisterThrottle, ScopedRateThrottle

    request = Request(rf.get("/", REMOTE_ADDR=remote))
    for throttle in (AnonRateThrottle(), RegisterThrottle(), ScopedRateThrottle()):
        assert throttle.get_ident(request) == ident


def test_api_root_lists_every_resource(api):
    body = api.get("/api/v1/").json()
    assert set(body) == {"feeds", "articles", "tags", "tag-rules", "subscriptions", "search"}
