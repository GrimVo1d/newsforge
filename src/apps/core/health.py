from __future__ import annotations

import redis
from django.conf import settings
from django.db import connection
from django.http import HttpResponse, JsonResponse
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class LiveView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})


class ReadyView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request: Request) -> Response:
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
            db_ok = True
        except Exception:
            db_ok = False
        try:
            r = redis.Redis.from_url(settings.CACHES["default"]["LOCATION"])
            redis_ok = bool(r.ping())
        except Exception:
            redis_ok = False
        ok = db_ok and redis_ok
        return Response({"db": db_ok, "redis": redis_ok}, status=200 if ok else 503)


def metrics_view(request) -> HttpResponse:  # type: ignore[no-untyped-def]
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return HttpResponse(generate_latest(), content_type=CONTENT_TYPE_LATEST)


# JsonResponse imported for downstream extensions (unused here, kept for type stability).
_ = JsonResponse
