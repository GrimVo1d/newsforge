from .base import *  # noqa: F403
from .base import env

DEBUG = False

# No defaults: a missing value must fail at startup instead of falling back to something public.
SECRET_KEY = env("SECRET_KEY")
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
