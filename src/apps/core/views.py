from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(min_length=8, write_only=True)
    email = serializers.EmailField(required=False, allow_blank=True)


class RegisterView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        s = RegisterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        User = get_user_model()
        if User.objects.filter(username=s.validated_data["username"]).exists():
            return Response(
                {"code": "username_taken", "detail": "Username already taken."},
                status=status.HTTP_409_CONFLICT,
            )
        user = User.objects.create_user(
            username=s.validated_data["username"],
            password=s.validated_data["password"],
            email=s.validated_data.get("email") or "",
        )
        return Response({"id": user.pk, "username": user.username}, status=status.HTTP_201_CREATED)
