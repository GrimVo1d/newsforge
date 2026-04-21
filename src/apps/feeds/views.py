from __future__ import annotations

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.request import Request
from rest_framework.response import Response

from apps.feeds.models import Feed
from apps.feeds.serializers import FeedSerializer


class FeedViewSet(viewsets.ModelViewSet):
    queryset = Feed.objects.filter(is_deleted=False)
    serializer_class = FeedSerializer
    permission_classes = (IsAuthenticatedOrReadOnly,)
    filterset_fields = ("language", "is_active")

    def perform_create(self, serializer: FeedSerializer) -> None:
        serializer.save(next_fetch_at=timezone.now())

    def perform_destroy(self, instance: Feed) -> None:
        instance.is_deleted = True
        instance.is_active = False
        instance.save(update_fields=["is_deleted", "is_active", "updated_at"])

    @action(detail=True, methods=["post"], url_path="refresh")
    def refresh(self, request: Request, pk: int | None = None) -> Response:
        feed = self.get_object()
        feed.next_fetch_at = timezone.now()
        feed.save(update_fields=["next_fetch_at", "updated_at"])
        return Response({"queued_at": feed.next_fetch_at.isoformat()}, status=status.HTTP_202_ACCEPTED)
