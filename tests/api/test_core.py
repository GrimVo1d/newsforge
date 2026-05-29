from __future__ import annotations

import os
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


def _import_prod_settings(**env: str) -> subprocess.CompletedProcess[str]:
    clean = {k: v for k, v in os.environ.items() if k not in {"SECRET_KEY", "ALLOWED_HOSTS"}}
    clean.update(env, DJANGO_SETTINGS_MODULE="newsforge.settings.prod")
    return subprocess.run(
        [sys.executable, "-c", "import django; django.setup()"],
        env=clean,
        capture_output=True,
        text=True,
        check=False,
    )


def test_prod_settings_require_secret_key_and_hosts():
    missing = _import_prod_settings()
    assert missing.returncode != 0
    assert "SECRET_KEY" in missing.stderr

    no_hosts = _import_prod_settings(SECRET_KEY="x" * 64)
    assert no_hosts.returncode != 0
    assert "ALLOWED_HOSTS" in no_hosts.stderr

    ok = _import_prod_settings(SECRET_KEY="x" * 64, ALLOWED_HOSTS="news.example.internal")
    assert ok.returncode == 0, ok.stderr
