#!/bin/sh
set -eu

cmd="${1:-api}"

case "$cmd" in
  api)
    exec python -m gunicorn \
      --bind 0.0.0.0:8000 \
      --workers "${GUNICORN_WORKERS:-4}" \
      --access-logfile - \
      --error-logfile - \
      newsforge.wsgi:application
    ;;
  worker)
    exec celery -A newsforge worker \
      --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
      --queues="${CELERY_QUEUES:-default,low}" \
      --concurrency="${CELERY_CONCURRENCY:-16}"
    ;;
  beat)
    exec celery -A newsforge beat --loglevel="${CELERY_LOG_LEVEL:-INFO}"
    ;;
  migrate)
    exec python manage.py migrate --noinput
    ;;
  *)
    exec "$@"
    ;;
esac
