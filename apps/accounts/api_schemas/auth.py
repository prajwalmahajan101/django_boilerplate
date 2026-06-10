"""OpenAPI schemas for the Google OAuth / JWT token-refresh / logout endpoints."""

from accounts.api_schemas._common import (
    _auth_required_schema,
    _error_response_schema,
    _jwt_token_pair_schema,
    _throttled_response_schema,
    _validation_error_schema,
)
from accounts.serializers import GoogleCallbackSerializer
from core.api_schemas import throttle_response
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, inline_serializer
from rest_framework import serializers

# ---------------------------------------------------------------------------
# POST /api/accounts/auth/google/
# ---------------------------------------------------------------------------

google_login_schema = {
    "operation_id": "auth_google_login",
    "summary": "Google OAuth login",
    "description": (
        "Exchange a Google authorization code for JWT access and refresh tokens.\n\n"
        "The frontend obtains an authorization code from Google's OAuth consent screen "
        "and sends it here along with the redirect URI that was used. The backend "
        "exchanges the code for Google tokens via allauth, creates or links the user "
        "account, and returns a JWT token pair.\n\n"
        "**Rate limit:** 20 requests/hour per IP."
    ),
    "request": GoogleCallbackSerializer,
    "responses": {
        200: OpenApiResponse(
            description="Login successful. Returns JWT token pair and user profile.",
            response=_jwt_token_pair_schema,
        ),
        400: OpenApiResponse(
            description="Invalid request — missing or invalid fields, or Google code exchange failed.",
            response=_validation_error_schema,
            examples=[
                OpenApiExample(
                    name="missing_fields",
                    value={"code": ["This field is required."]},
                    description="Required fields missing from request body",
                ),
                OpenApiExample(
                    name="invalid_redirect_uri",
                    value={"redirect_uri": ["Enter a valid URL."]},
                    description="redirect_uri is not a valid URL",
                ),
            ],
        ),
        429: OpenApiResponse(
            description="Rate limit exceeded (20 requests/hour per IP).",
            response=_throttled_response_schema,
            examples=[
                OpenApiExample(
                    name="throttled",
                    value={
                        "detail": "Request was throttled. Expected available in 3600 seconds.",
                    },
                ),
            ],
        ),
    },
    "tags": ["Auth"],
}

# ---------------------------------------------------------------------------
# POST /api/accounts/auth/token/refresh/
# ---------------------------------------------------------------------------

token_refresh_schema = {
    "operation_id": "auth_token_refresh",
    "summary": "Refresh JWT access token",
    "description": (
        "Submit a valid refresh token to receive a new access/refresh token pair.\n\n"
        "Tokens are rotated on each refresh: the old refresh token is blacklisted "
        "and a new pair is issued.\n\n"
        "**Rate limit:** 20 requests/hour per IP."
    ),
    "request": inline_serializer(
        name="TokenRefreshRequest",
        fields={
            "refresh": serializers.CharField(
                help_text="JWT refresh token obtained from login or a previous refresh.",
            ),
        },
    ),
    "responses": {
        200: OpenApiResponse(
            description="Token refreshed successfully.",
            response=_jwt_token_pair_schema,
            examples=[
                OpenApiExample(
                    name="success",
                    value={
                        "access": "eyJhbGciOiJIUzI1NiIs...",
                        "refresh": "eyJhbGciOiJIUzI1NiIs...",
                    },
                ),
            ],
        ),
        400: OpenApiResponse(
            description="Refresh token not provided in request body.",
            response=_error_response_schema,
            examples=[
                OpenApiExample(
                    name="missing_refresh",
                    value={"success": False, "message": "Refresh token is required."},
                ),
            ],
        ),
        401: OpenApiResponse(
            description="Refresh token is invalid or expired.",
            response=_error_response_schema,
            examples=[
                OpenApiExample(
                    name="invalid_refresh",
                    value={"success": False, "message": "Token is invalid or expired."},
                ),
            ],
        ),
        429: OpenApiResponse(
            description="Rate limit exceeded (20 requests/hour per IP).",
            response=_throttled_response_schema,
            examples=[
                OpenApiExample(
                    name="throttled",
                    value={
                        "detail": "Request was throttled. Expected available in 3600 seconds.",
                    },
                ),
            ],
        ),
    },
    "tags": ["Auth"],
}

# ---------------------------------------------------------------------------
# POST /api/accounts/auth/logout/
# ---------------------------------------------------------------------------

logout_schema = {
    "operation_id": "auth_logout",
    "summary": "Logout (blacklist refresh token)",
    "description": (
        "Blacklist the provided refresh token so it can no longer be used to "
        "obtain new access tokens. The client should also discard the access token.\n\n"
        "**Authentication:** Bearer JWT required."
    ),
    "request": inline_serializer(
        name="LogoutRequest",
        fields={
            "refresh": serializers.CharField(
                help_text="JWT refresh token to blacklist.",
            ),
        },
    ),
    "responses": {
        200: OpenApiResponse(
            description="Successfully logged out.",
            response={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "example": "Successfully logged out."},
                },
            },
            examples=[
                OpenApiExample(
                    name="success",
                    value={"message": "Successfully logged out."},
                ),
            ],
        ),
        400: OpenApiResponse(
            description="Refresh token missing.",
            response=_error_response_schema,
            examples=[
                OpenApiExample(
                    name="missing_refresh",
                    value={"success": False, "message": "Refresh token is required."},
                ),
            ],
        ),
        401: OpenApiResponse(
            description="Authentication required or token invalid.",
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
