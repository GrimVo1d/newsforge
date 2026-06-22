import secrets

from .base import *  # noqa: F403
from .base import REST_FRAMEWORK

DEBUG = False
# Random per run: a fixed key here would be public and could end up in a real deployment.
SECRET_KEY = secrets.token_urlsafe(50)
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
METRICS_TOKEN = "test-metrics-token"

# Throttle counters live in Redis and would leak between tests; tests that exercise
# throttling override the rates explicitly.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {
        "anon": None,
        "user": None,
        "auth": None,
        "register": None,
        "search": None,
    },
}
