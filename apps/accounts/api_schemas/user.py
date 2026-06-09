"""OpenAPI schemas for the GET / PATCH /api/accounts/auth/me/ endpoints."""

from accounts.api_schemas._common import (
    _auth_required_schema,
    _error_response_schema,
)
from accounts.serializers import UserProfileSerializer
from core.api_schemas import throttle_response
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, inline_serializer
from rest_framework import serializers

_user_profile_example = {
    "id": 1,
    "email": "user@example.com",
    "first_name": "Jane",
    "last_name": "Doe",
    "full_name": "Jane Doe",
    "avatar_url": "https://lh3.googleusercontent.com/a/photo",
    "roles": [
        {"id": 1, "name": "user", "description": "Default user role"},
    ],
    "timezone": "Asia/Kolkata",
    "email_verified": True,
    "date_joined": "2025-01-15T10:30:00Z",
    "last_login": "2025-06-01T14:22:00Z",
    "google_connected": True,
}

me_get_schema = {
    "operation_id": "auth_me_retrieve",
    "summary": "Get current user profile",
    "description": (
        "Returns the authenticated user's profile including roles and social account status.\n\n"
        "**Authentication:** Bearer JWT required."
    ),
    "responses": {
        200: OpenApiResponse(
            response=UserProfileSerializer,
            description="User profile retrieved successfully.",
            examples=[
                OpenApiExample(
                    name="success",
                    value=_user_profile_example,
                    description="Complete user profile with roles and social status",
                ),
            ],
        ),
        401: OpenApiResponse(
            description="Authentication required.",
            response=_auth_required_schema,
            examples=[
                OpenApiExample(
                    name="unauthorized",
                    value={"detail": "Authentication credentials were not provided."},
                ),
            ],
        ),
        429: throttle_response,
    },
    "tags": ["Auth"],
}

me_patch_schema = {
    "operation_id": "auth_me_partial_update",
    "summary": "Update current user profile",
    "description": (
        "Update the authenticated user's profile. Only `timezone`, `first_name`, "
        "and `last_name` are accepted; other fields are ignored.\n\n"
        "**Authentication:** Bearer JWT required."
    ),
    "request": inline_serializer(
        name="MeUpdateRequest",
        fields={
            "timezone": serializers.CharField(
                required=False,
                help_text="IANA timezone identifier.",
            ),
            "first_name": serializers.CharField(
                required=False,
                help_text="User's first name.",
            ),
            "last_name": serializers.CharField(
                required=False,
                help_text="User's last name.",
            ),
        },
    ),
    "responses": {
        200: OpenApiResponse(
            response=UserProfileSerializer,
            description="Profile updated successfully.",
            examples=[
                OpenApiExample(
                    name="success",
                    value=_user_profile_example,
                    description="Updated user profile",
                ),
            ],
        ),
        400: OpenApiResponse(
            description="No valid fields provided.",
            response=_error_response_schema,
            examples=[
                OpenApiExample(
                    name="no_fields",
                    value={"success": False, "message": "No valid fields provided."},
                ),
            ],
        ),
        401: OpenApiResponse(
            description="Authentication required.",
            response=_auth_required_schema,
            examples=[
                OpenApiExample(
                    name="unauthorized",
                    value={"detail": "Authentication credentials were not provided."},
                ),
            ],
        ),
        429: throttle_response,
    },
    "tags": ["Auth"],
}
