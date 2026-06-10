from __future__ import annotations

import hmac

from django.conf import settings
from django.db import connection
from django.http import Http404, HttpRequest, HttpResponse
from drf_spectacular.utils import extend_schema, inline_serializer
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.feeds.ratelimit import redis_client


class LiveView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = ()
    renderer_classes = (JSONRenderer,)

    @extend_schema(
        responses=inline_serializer("Live", {"status": serializers.CharField()}),
    )
    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})


class ReadyView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = ()
    renderer_classes = (JSONRenderer,)

    @extend_schema(
        responses=inline_serializer(
            "Ready", {"db": serializers.BooleanField(), "redis": serializers.BooleanField()}
        ),
    )
    def get(self, request: Request) -> Response:
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT 1;")
            db_ok = True
        except Exception:
            db_ok = False
        try:
            redis_ok = bool(redis_client().ping())
        except Exception:
            redis_ok = False
        ok = db_ok and redis_ok
        return Response({"db": db_ok, "redis": redis_ok}, status=200 if ok else 503)


def metrics_view(request: HttpRequest) -> HttpResponse:
    """Prometheus exposition, guarded by a bearer token; hidden entirely when none is set."""
    token = settings.METRICS_TOKEN
    scheme, _, supplied = request.headers.get("Authorization", "").partition(" ")
    if (
        not token
        or scheme != "Bearer"
        or not hmac.compare_digest(supplied.encode(), token.encode())
    ):
        raise Http404
    return HttpResponse(generate_latest(), content_type=CONTENT_TYPE_LATEST)
