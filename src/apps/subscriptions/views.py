from __future__ import annotations

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.pagination import LimitOffsetPagination
from apps.subscriptions.models import DeliveryLog, Subscription, new_webhook_secret
from apps.subscriptions.serializers import (
    DeliveryLogSerializer,
    SubscriptionSerializer,
    WebhookSecretSerializer,
)


class SubscriptionViewSet(viewsets.ModelViewSet[Subscription]):
    serializer_class = SubscriptionSerializer
    permission_classes = (permissions.IsAuthenticated,)
    queryset = Subscription.objects.none()  # schema generation; real rows come from get_queryset

    def get_queryset(self) -> QuerySet[Subscription]:
        if getattr(self, "swagger_fake_view", False):
            return Subscription.objects.none()
        return Subscription.objects.filter(owner_id=self.request.user.pk).order_by("-created_at")

    @extend_schema(request=None, responses=WebhookSecretSerializer)
    @action(detail=True, methods=["post"], url_path="rotate-secret")
    def rotate_secret(self, request: Request, pk: str | None = None) -> Response:
        sub = self.get_object()
        if sub.delivery != Subscription.Delivery.WEBHOOK:
            raise serializers.ValidationError(
                {"delivery": "only webhook subscriptions have a secret"}
            )
        sub.webhook_secret = new_webhook_secret()
        sub.save(update_fields=["webhook_secret"])
        return Response({"webhook_secret": sub.webhook_secret})

    @extend_schema(responses=DeliveryLogSerializer(many=True))
    @action(detail=True, methods=["get"])
    def deliveries(self, request: Request, pk: str | None = None) -> Response:
        sub = self.get_object()
        # By id, not delivered_at: retries update delivered_at and would reshuffle the pages.
        rows = DeliveryLog.objects.filter(subscription=sub).order_by("-id")
        paginator = LimitOffsetPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(DeliveryLogSerializer(page, many=True).data)
