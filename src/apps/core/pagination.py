from __future__ import annotations

from rest_framework import pagination, serializers
from rest_framework.request import Request

MAX_OFFSET = 10_000


class LimitOffsetPagination(pagination.LimitOffsetPagination):
    max_limit = 100

    def get_offset(self, request: Request) -> int:
        # Deep offsets make PostgreSQL walk and drop every skipped row; filter instead.
        offset = super().get_offset(request)
        if offset > MAX_OFFSET:
            raise serializers.ValidationError({"offset": [f"at most {MAX_OFFSET}"]})
        return offset
