from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

# Production by default, like wsgi.py / asgi.py: this module is imported first (from the package
# __init__), so a dev default here would win for gunicorn too. manage.py defaults to dev.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "newsforge.settings.prod")

TASK_MODULES = (
    "tasks.articles",
    "tasks.digest",
    "tasks.fetcher",
    "tasks.notifications",
    "tasks.scheduler",
    "tasks.tags",
)

app = Celery("newsforge", include=TASK_MODULES)
app.config_from_object("django.conf:settings", namespace="CELERY")

app.conf.beat_schedule = {
    "enqueue-due-feeds": {
        "task": "tasks.scheduler.enqueue_due_feeds",
        "schedule": 60.0,
        "options": {"queue": "default"},
    },
    "daily-digest": {
        "task": "tasks.digest.daily_digest",
        "schedule": crontab(hour=9, minute=0),
        "options": {"queue": "low"},
    },
    "refresh-robots-cache": {
        "task": "tasks.scheduler.refresh_robots_cache",
        "schedule": crontab(hour=4, minute=0),
        "options": {"queue": "low"},
    },
    "cleanup-old-articles": {
        "task": "tasks.scheduler.cleanup_old_articles",
        "schedule": crontab(day_of_week=0, hour=3, minute=0),
        "options": {"queue": "low"},
    },
}

app.conf.task_routes = {
    "tasks.fetcher.*": {"queue": "default"},
    "tasks.articles.*": {"queue": "default"},
    "tasks.tags.*": {"queue": "default"},
    "tasks.notifications.*": {"queue": "default"},
    "tasks.digest.*": {"queue": "low"},
    "tasks.scheduler.*": {"queue": "low"},
}
