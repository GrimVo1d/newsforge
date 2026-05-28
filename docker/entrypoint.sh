#!/bin/sh
set -eu

cmd="${1:-api}"

case "$cmd" in
  api)
    exec gunicorn newsforge.wsgi:application \
      --bind 0.0.0.0:8000 \
      --workers "${GUNICORN_WORKERS:-4}" \
      --no-control-socket \
      --access-logfile - \
      --error-logfile -
    ;;
  worker)
    exec celery -A newsforge worker \
      --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
      --queues="${CELERY_QUEUES:-default,low}" \
      --concurrency="${CELERY_CONCURRENCY:-4}"
    ;;
  beat)
    exec celery -A newsforge beat \
      --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
      --schedule=/tmp/celerybeat-schedule
    ;;
  migrate)
    exec python manage.py migrate --noinput
    ;;
  *)
    exec "$@"
    ;;
esac
