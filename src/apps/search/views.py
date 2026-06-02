from __future__ import annotations

from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from apps.search.queries import run_search
from apps.search.serializers import SearchParamsSerializer, SearchResponseSerializer

_RENAMED = {"from": "date_from", "to": "date_to"}


class SearchView(APIView):
    permission_classes = (AllowAny,)
    throttle_classes = (AnonRateThrottle, UserRateThrottle, ScopedRateThrottle)
    throttle_scope = "search"

    @extend_schema(
        parameters=[
            SearchParamsSerializer(),
            OpenApiParameter("from", OpenApiTypes.DATETIME, description="published_at >= from"),
            OpenApiParameter("to", OpenApiTypes.DATETIME, description="published_at < to"),
        ],
        responses=SearchResponseSerializer,
    )
    def get(self, request: Request) -> Response:
        params = request.query_params.copy()
        for public, internal in _RENAMED.items():
            if public in params:
                params.setlist(internal, params.pop(public))
            else:
                params.pop(internal, None)
        s = SearchParamsSerializer(data=params)
        s.is_valid(raise_exception=True)
        p: dict[str, Any] = s.validated_data

        query = p["q"].strip()
        if not query:
            return Response({"count": 0, "results": []})
        rows = run_search(
            query=query,
            lang=p.get("lang"),
            sort=p["sort"],
            feeds=p["feed"],
            date_from=p.get("date_from"),
            date_to=p.get("date_to"),
            limit=p["limit"],
            offset=p["offset"],
        )
        return Response({"count": len(rows), "results": rows})
