from __future__ import annotations

from django.db.models import QuerySet
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.permissions import IsStaffOrReadOnly
from apps.feeds.models import Feed
from apps.feeds.serializers import FeedSerializer, PublicFeedSerializer


class FeedViewSet(viewsets.ModelViewSet[Feed]):
    """Feeds are shared by all users: everyone reads them, staff manage them."""

    queryset = Feed.objects.filter(is_deleted=False).order_by("id")
    permission_classes = (IsStaffOrReadOnly,)
    filterset_fields = ("language", "is_active")

    def get_queryset(self) -> QuerySet[Feed]:
        qs = super().get_queryset()
        if not self.request.user.is_staff:
            qs = qs.filter(is_active=True)
        return qs

    def get_serializer_class(self) -> type[serializers.BaseSerializer[Feed]]:
        if getattr(self, "swagger_fake_view", False):
            # Schema: reads as everyone sees them, writes as staff send them.
            return PublicFeedSerializer if self.action in ("list", "retrieve") else FeedSerializer
        if self.request.user.is_staff:
            return FeedSerializer
        return PublicFeedSerializer

    def perform_create(self, serializer: serializers.BaseSerializer[Feed]) -> None:
        serializer.save(next_fetch_at=timezone.now())

    def perform_destroy(self, instance: Feed) -> None:
        instance.is_deleted = True
        instance.is_active = False
        instance.save(update_fields=["is_deleted", "is_active", "updated_at"])

    @action(detail=True, methods=["post"], url_path="refresh")
    def refresh(self, request: Request, pk: str | None = None) -> Response:
        feed = self.get_object()
        feed.next_fetch_at = timezone.now()
        feed.disabled_until = None  # an explicit refresh also ends a pause
        feed.save(update_fields=["next_fetch_at", "disabled_until", "updated_at"])
        return Response(
            {"queued_at": feed.next_fetch_at.isoformat()},
            status=status.HTTP_202_ACCEPTED,
        )
