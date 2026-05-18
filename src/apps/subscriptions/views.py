from __future__ import annotations

from rest_framework import permissions, viewsets

from apps.subscriptions.models import Subscription
from apps.subscriptions.serializers import SubscriptionSerializer


class SubscriptionViewSet(viewsets.ModelViewSet):
    serializer_class = SubscriptionSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):  # type: ignore[no-untyped-def]
        return Subscription.objects.filter(owner=self.request.user).order_by("-created_at")
