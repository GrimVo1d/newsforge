from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import DEV_SECRET_KEY, env

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
):
    raise ImproperlyConfigured(
        "SECRET_KEY must be a random string of at least 50 characters "
        "(e.g. python -c 'import secrets; print(secrets.token_urlsafe(64))')"
    )
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")

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
