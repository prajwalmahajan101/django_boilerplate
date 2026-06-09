"""Auth serializers for user profiles and Google OAuth callback."""

from __future__ import annotations

from accounts.models import Role, User
from rest_framework import serializers


class RoleSerializer(serializers.ModelSerializer):
    """Serializer for Role model."""

    class Meta:
        model = Role
        fields = ["id", "name", "description"]
        read_only_fields = fields


class UserSerializer(serializers.ModelSerializer):
    """Serializer for user details (used by dj-rest-auth USER_DETAILS_SERIALIZER)."""

    roles = RoleSerializer(many=True, read_only=True)
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "avatar_url",
            "roles",
            "timezone",
            "email_verified",
            "date_joined",
            "last_login",
        ]
        read_only_fields = [
            "id",
            "email",
            "full_name",
            "avatar_url",
            "roles",
            "email_verified",
            "date_joined",
            "last_login",
        ]


class UserProfileSerializer(UserSerializer):
    """Extended user serializer with social account info.

    Note: If this serializer is used in a list view, the queryset MUST include
    ``prefetch_related("socialaccount_set")`` to avoid N+1 queries from
    ``get_google_connected()``.  Currently safe because /me is single-user only.
    """

    google_connected = serializers.SerializerMethodField()

    class Meta(UserSerializer.Meta):
        fields = [*UserSerializer.Meta.fields, "google_connected"]

    def get_google_connected(self, obj: User) -> bool:
        """Return True if user has a linked Google social account."""
        return obj.socialaccount_set.filter(provider="google").exists()


class GoogleCallbackSerializer(serializers.Serializer):
    """Validates the Google OAuth callback payload from the frontend."""

    code = serializers.CharField(required=True, help_text="Authorization code from Google")
    redirect_uri = serializers.URLField(
        required=True, help_text="Redirect URI used in the OAuth flow"
    )

    def validate_redirect_uri(self, value: str) -> str:
        """Validate redirect_uri against configured allowlist.

        Defense-in-depth: Google's server also validates redirect URIs,
        but we should not rely solely on the OAuth provider.
        """
        from django.conf import settings

        allowed = getattr(settings, "GOOGLE_OAUTH_ALLOWED_REDIRECT_URIS", None)
        if not allowed:
            # Fail-closed in all environments: empty allowlist = reject all.
            raise serializers.ValidationError(
                "OAuth redirect URI allowlist is not configured. "
                "Set GOOGLE_OAUTH_ALLOWED_REDIRECT_URIS in your environment."
            )
        if value not in allowed:
            raise serializers.ValidationError("Redirect URI is not permitted.")
        return value


class CustomJWTSerializer(serializers.Serializer):
    """JWT response serializer that always includes refresh token in the body.

    dj-rest-auth's default JWTSerializer omits the refresh token from the
    JSON body when JWT_AUTH_HTTPONLY is True (it only sets the HttpOnly cookie).
    This serializer overrides that behavior so the frontend receives the
    refresh token in both the cookie AND the response body.
    """

    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)
    user = serializers.SerializerMethodField()

    def get_user(self, obj):
        """Return serialized user data using the configured USER_DETAILS_SERIALIZER."""
        user = obj.get("user")
        if not user:
            return None
        return UserSerializer(user, context=self.context).data

    def validate(self, attrs):
        return attrs

    @classmethod
    def get_token(cls, data):
        return data

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Ensure access_expiration and refresh_expiration are included
        # when JWT_AUTH_RETURN_EXPIRATION is True.
        if "access_expiration" in instance:
            data["access_expiration"] = instance["access_expiration"]
        if "refresh_expiration" in instance:
            data["refresh_expiration"] = instance["refresh_expiration"]
        return data
