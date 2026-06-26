from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.core.throttling import RegisterThrottle, ScopedRateThrottle


class RegisterSerializer(serializers.Serializer[Any]):
    username = serializers.CharField(max_length=150, validators=[UnicodeUsernameValidator()])
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    email = serializers.EmailField(required=False, allow_blank=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        user = get_user_model()(username=attrs["username"], email=attrs.get("email", ""))
        try:
            password_validation.validate_password(attrs["password"], user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc
        return attrs


class RegisterView(APIView):
    permission_classes = (AllowAny,)
    throttle_classes = (ScopedRateThrottle, RegisterThrottle)
    throttle_scope = "auth"
    serializer_class = RegisterSerializer

    def post(self, request: Request) -> Response:
        s = RegisterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                user = get_user_model().objects.create_user(
                    username=s.validated_data["username"],
                    password=s.validated_data["password"],
                    email=s.validated_data.get("email") or "",
                )
        except IntegrityError:
            return Response(
                {"code": "username_taken", "detail": "Username already taken."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response({"id": user.pk, "username": user.username}, status=status.HTTP_201_CREATED)


class TokenView(TokenObtainPairView):
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "auth"


class TokenRefreshThrottledView(TokenRefreshView):
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "auth"
