"""Shared Django settings for newsforge."""

from __future__ import annotations

from datetime import timedelta

import environ

env = environ.Env()

# No usable default here: dev.py and test.py set their own key, prod.py requires a real one.
# The dev key is named so prod.py can refuse it.
DEV_SECRET_KEY = "dev-only-insecure-secret-key-do-not-use-in-prod"
SECRET_KEY = env("SECRET_KEY", default="")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "drf_spectacular",
    "django_filters",
    "apps.core",
    "apps.feeds",
    "apps.articles",
    "apps.tags",
    "apps.search",
    "apps.subscriptions",
]

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}

MIDDLEWARE = [
    # First: probes reach /health/* by IP over plain http, before host checks and redirects.
    "apps.core.middleware.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "newsforge.urls"
WSGI_APPLICATION = "newsforge.wsgi.application"
ASGI_APPLICATION = "newsforge.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

DATABASES = {"default": env.db("DATABASE_URL", default="postgres://nf:nf@db:5432/newsforge")}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://redis:6379/0"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": f"django.contrib.auth.password_validation.{name}"}
    for name in (
        "UserAttributeSimilarityValidator",
        "MinimumLengthValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    )
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
CSRF_FAILURE_VIEW = "apps.core.exceptions.csrf_failure"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticatedOrReadOnly",),
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_CLASSES": (
        "apps.core.throttling.AnonRateThrottle",
        "apps.core.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("THROTTLE_ANON", default="120/min"),
        "user": env("THROTTLE_USER", default="600/min"),
        # register / token endpoints (ScopedRateThrottle)
        "auth": env("THROTTLE_AUTH", default="10/min"),
        # account creation per client address, on top of "auth"
        "register": env("THROTTLE_REGISTER", default="20/day"),
        "search": env("THROTTLE_SEARCH", default="60/min"),
    },
    # Throttles key anonymous clients by address (apps.core.throttling: an IPv6 client by its
    # /64). With NUM_PROXIES unset DRF would use the whole client-supplied X-Forwarded-For
    # header, so every request could pick its own bucket.
    # 0 = use REMOTE_ADDR; N = take the address appended by the N-th trusted proxy.
    "NUM_PROXIES": env.int("NUM_PROXIES", default=0),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.envelope",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "newsforge API",
    "DESCRIPTION": "RSS/Atom aggregator with PG full-text search",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# Prometheus metrics are served only with "Authorization: Bearer <METRICS_TOKEN>".
METRICS_TOKEN = env("METRICS_TOKEN", default="")

# Crawler tunables
USER_AGENT = env("USER_AGENT", default="newsforge/0.1")
HTTP_TIMEOUT = env.int("HTTP_TIMEOUT", default=20)
MAX_RESPONSE_BYTES = env.int("MAX_RESPONSE_BYTES", default=5_242_880)
# Entries taken from one fetch; the rest of an oversized feed is ignored.
MAX_ENTRIES_PER_FETCH = env.int("MAX_ENTRIES_PER_FETCH", default=200)
MIN_FEED_INTERVAL_SECONDS = 300
MAX_SUBSCRIPTIONS_PER_USER = env.int("MAX_SUBSCRIPTIONS_PER_USER", default=20)
# How many accounts may deliver to one email address or webhook URL.
MAX_ACCOUNTS_PER_TARGET = env.int("MAX_ACCOUNTS_PER_TARGET", default=5)
# Allow plain-http feed / webhook URLs (https only by default).
ALLOW_PLAIN_HTTP = env.bool("ALLOW_PLAIN_HTTP", default=False)
PER_DOMAIN_MIN_INTERVAL = env.int("PER_DOMAIN_MIN_INTERVAL", default=30)

# Email (subscription delivery)
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="no-reply@newsforge.local")

# Celery
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://redis:6379/1")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://redis:6379/2")
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_SOFT_TIME_LIMIT = env.int("CELERY_TASK_SOFT_TIME_LIMIT", default=60)
CELERY_TASK_TIME_LIMIT = env.int("CELERY_TASK_TIME_LIMIT", default=90)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    # httpx logs every request at INFO, with the pinned IP instead of the host name
    "loggers": {"httpx": {"level": "WARNING"}},
}
