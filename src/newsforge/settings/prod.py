import hashlib

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import CACHES, DEV_SECRET_KEY, REST_FRAMEWORK, env

# sha256 of random-looking keys that were committed to this repository (test fixtures): they
# are public, so anyone could sign tokens with them.
PUBLIC_KEY_HASHES = frozenset(
    {
        "8e83ff75d6fc340c1911cd554bcba6a93275ec3bb245d98c89aed53abf3882d2",
        "b38a92f368260dd8488ffb05ac1e29b110c3b162f6bcc6467f99771ee1151b64",
    }
)

DEBUG = False

# No defaults: a missing value must fail at startup instead of falling back to something public.
SECRET_KEY = env("SECRET_KEY")
# The same bar as Django's security.W009, enforced instead of only reported by check --deploy.
if (
    len(SECRET_KEY) < 50
    or len(set(SECRET_KEY)) < 5
    or SECRET_KEY.startswith("django-insecure-")
    or SECRET_KEY == DEV_SECRET_KEY
    # Placeholders that were committed to this repository at some point.
    or any(marker in SECRET_KEY.lower() for marker in ("insecure", "test-only"))
    or hashlib.sha256(SECRET_KEY.encode()).hexdigest() in PUBLIC_KEY_HASHES
):
    raise ImproperlyConfigured(
        "SECRET_KEY must be a random string of at least 50 characters "
        "(e.g. python -c 'import secrets; print(secrets.token_urlsafe(64))')"
    )
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")

# The dev defaults in base (nf:nf@db, password-less redis) must not be used silently.
DATABASES = {"default": env.db("DATABASE_URL")}
CACHES = {"default": {**CACHES["default"], "LOCATION": env("REDIS_URL")}}
CELERY_BROKER_URL = env("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND")

# JSON only: the browsable API is a development aid.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
}

SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Trust X-Forwarded-Proto only when a TLS-terminating proxy is guaranteed to set it.
if env.bool("TRUST_X_FORWARDED_PROTO", default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if not SECURE_HSTS_PRELOAD:
    # Preload is an opt-in commitment for the whole domain.
    SILENCED_SYSTEM_CHECKS = ["security.W021"]
