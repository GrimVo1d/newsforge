from __future__ import annotations

from datetime import datetime

from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.search.queries import run_search


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


class SearchView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request: Request) -> Response:
        q = (request.query_params.get("q") or "").strip()
        if not q:
            return Response({"count": 0, "results": []})
        lang = request.query_params.get("lang")
        sort = request.query_params.get("sort", "rank")
        feeds_raw = request.query_params.getlist("feed")
        feeds = [int(f) for f in feeds_raw if f.isdigit()]
        limit = min(int(request.query_params.get("limit", 20)), 100)
        offset = int(request.query_params.get("offset", 0))

        rows = run_search(
            query=q,
            lang=lang,
            sort=sort,
            feeds=feeds,
            date_from=_parse_dt(request.query_params.get("from")),
            date_to=_parse_dt(request.query_params.get("to")),
            limit=limit,
            offset=offset,
        )
        return Response({"count": len(rows), "results": rows})
