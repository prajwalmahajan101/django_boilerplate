"""Auth views: Google OAuth login, token refresh, logout, user profile."""

from __future__ import annotations

import logging

from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from dj_rest_auth.registration.views import SocialLoginView
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.api_schemas import (
    api_key_delete_schema,
    api_key_revoke_schema,
    google_login_schema,
    logout_schema,
    me_get_schema,
    me_patch_schema,
    token_refresh_schema,
)
from accounts.repositories import UserRepository
from accounts.serializers import GoogleCallbackSerializer, UserProfileSerializer
from accounts.services import APIKeyService, UserService
from core.enums import Action, Resource
from core.middleware.throttling import AuthEndpointThrottle
from core.permissions import HasResourcePermission
from core.responses import ErrorResponse, SuccessResponse
from rest_framework.throttling import AnonRateThrottle
from resilience_kit.adapters.django.drf_throttles import BurstThrottle

logger = logging.getLogger(__name__)


class AuthThrottle(AnonRateThrottle):
    """Sustained auth-endpoint rate limit: 20 requests/hour per IP.

    Complements ``AuthEndpointThrottle`` (5/min burst). The 20/hour rate
    is published under ``DEFAULT_THROTTLE_RATES["auth"]`` so DRF's
    ``AnonRateThrottle.get_rate`` picks it up via the ``auth`` scope.
    Sustained brute-force protection; the burst throttle handles the
    fast-cycling credential-stuffing pattern.
    """

    scope = "auth"


# AuthEndpointThrottle (imported above) is a DRF-level burst throttle.
# Complements AuthThrottle (Valkey-backed, 20/hour sustained) with a
# 5/min anonymous-IP cap — caught regardless of nginx coverage.
# Defence-in-depth against credential-stuffing bursts.


class GoogleLogin(SocialLoginView):
    """Exchange Google authorization code for JWT tokens.

    POST /api/accounts/auth/google/
    Body: {"code": "...", "redirect_uri": "..."}
    """

    adapter_class = GoogleOAuth2Adapter
    callback_url = None  # Set dynamically from request
    client_class = OAuth2Client
    # Explicit empty auth — public OAuth endpoint must not
    # inherit any authentication classes from DRF defaults.
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [BurstThrottle, AuthThrottle, AuthEndpointThrottle]

    def get_response(self):
        """Include refresh token in JSON body even when JWT_AUTH_HTTPONLY is True.

        dj-rest-auth's default get_response() sets data['refresh'] = ""
        when JWT_AUTH_HTTPONLY is True (refresh is only in the cookie).
        We override to always include the refresh token in the response
        body so the frontend can store it for programmatic refresh calls.
        The HttpOnly cookie is still set by the parent method.
        """
        response = super().get_response()
        # self.refresh_token is set by LoginView.login() via jwt_encode()
        if hasattr(self, "refresh_token") and self.refresh_token:
            response.data["refresh"] = str(self.refresh_token)
        return response

    @extend_schema(**google_login_schema)
    def post(self, request, *args, **kwargs):
        """Validate callback payload and delegate to allauth."""
        serializer = GoogleCallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        self.callback_url = serializer.validated_data["redirect_uri"]

        return super().post(request, *args, **kwargs)


@extend_schema(**token_refresh_schema)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([BurstThrottle, AuthThrottle, AuthEndpointThrottle])
def token_refresh(request: Request) -> Response:
    """Refresh JWT access token.

    POST /api/accounts/auth/token/refresh/
    Body: {"refresh": "..."}
    """
    refresh_token = request.data.get("refresh")
    if not refresh_token:
        return ErrorResponse(
            message="Refresh token is required",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        token = RefreshToken(refresh_token)
        user = UserRepository().get_by_id(int(token["user_id"]))
        if not user or not user.is_active:
            return ErrorResponse(
                message="Invalid or expired refresh token",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        # Blacklist the old refresh token FIRST. If we minted the new
        # pair first and then the blacklist write failed, the user
        # would briefly hold two valid refresh tokens — extending
        # session lifetime past intent (ISSUE-009).
        try:
            token.blacklist()
        except TokenError as exc:
            logger.error(
                "Refresh-token blacklist failed during rotation; refusing to mint new pair.",
                extra={"error": str(exc)},
            )
            return ErrorResponse(
                message="Token rotation temporarily unavailable. Please retry.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        new_token = RefreshToken.for_user(user)
        return SuccessResponse(
            data={
                "access": str(new_token.access_token),
                "refresh": str(new_token),
            },
        )
    except TokenError:
        return ErrorResponse(
            message="Invalid or expired refresh token",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


@extend_schema(**logout_schema)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([BurstThrottle, AuthThrottle, AuthEndpointThrottle])
def logout(request: Request) -> Response:
    """Blacklist refresh token to log out.

    POST /api/accounts/auth/logout/
    Body: {"refresh": "..."}
    """
    refresh_token = request.data.get("refresh")
    if not refresh_token:
        return ErrorResponse(
            message="Refresh token is required",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        token = RefreshToken(refresh_token)
        # Verify the token belongs to the authenticated user
        # before blacklisting — prevents one user from invalidating
        # another user's session. Use same generic message for ownership
        # mismatch and invalid tokens — distinct messages leak token validity.
        if int(token["user_id"]) != request.user.id:
            return ErrorResponse(
                message="Invalid or expired refresh token",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        token.blacklist()
        return SuccessResponse(message="Successfully logged out.")
    except (TokenError, ValueError):
        return ErrorResponse(
            message="Invalid or expired refresh token",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


@extend_schema(methods=["GET"], **me_get_schema)
@extend_schema(methods=["PATCH"], **me_patch_schema)
@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
@throttle_classes([BurstThrottle, AuthThrottle, AuthEndpointThrottle])
def me(request: Request) -> Response:
    """Get or update current user profile.

    GET  /api/accounts/auth/me/  — returns profile + roles
    PATCH /api/accounts/auth/me/ — update timezone, first_name, last_name
    """
    user = request.user

    if request.method == "GET":
        serializer = UserProfileSerializer(user)
        return SuccessResponse(data=serializer.data)

    # PATCH — delegate to UserService. NoFieldsToUpdateError and
    # InvalidTimezoneError are registered in AccountsConfig.ready() so
    # they surface through the DRF handler with the standard envelope
    # and the auto-derived error_code.
    updated_user = UserService().update_profile(user.id, request.data)
    serializer = UserProfileSerializer(updated_user)
    return SuccessResponse(data=serializer.data)


class APIKeyDeleteView(APIView):
    """DELETE /api/accounts/api-keys/<pk>/ — soft-delete an API key."""

    permission_classes = [HasResourcePermission]
    resource = Resource.API_KEY

    def initial(self, request, *args, **kwargs):
        self.action = Action.DELETE
        super().initial(request, *args, **kwargs)

    @api_key_delete_schema
    def delete(self, request, pk):
        deleted = APIKeyService().delete(pk, user=request.user)
        if not deleted:
            return ErrorResponse(
                message="API key not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        # 200, not 204: the universal-envelope contract carries a JSON body,
        # which is spec-illegal on 204 ("No Content") and rejected by some
        # proxies. 200 is the only status that satisfies the envelope.
        return SuccessResponse(message="API key deleted.")


class APIKeyRevokeView(APIView):
    """POST /api/accounts/api-keys/<pk>/revoke/ — soft-revoke an API key.

    Distinct from delete: the row stays around (audit trail intact), but
    ``revoked_at`` gets stamped and ``APIKeyAuthentication`` returns 401
    on the next request that presents the key. Delegates to
    ``APIKeyService.revoke`` which holds the ``select_for_update`` +
    ``@transaction.atomic`` boundary so concurrent revoke calls don't
    race on the timestamp.
    """

    permission_classes = [HasResourcePermission]
    resource = Resource.API_KEY

    def initial(self, request, *args, **kwargs):
        self.action = Action.UPDATE
        super().initial(request, *args, **kwargs)

    @api_key_revoke_schema
    def post(self, request, pk):
        revoked_now, already_revoked = APIKeyService().revoke(pk, user=request.user)
        if not revoked_now and not already_revoked:
            return ErrorResponse(
                message="API key not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        if already_revoked:
            return SuccessResponse(
                message="API key already revoked.",
                status_code=status.HTTP_200_OK,
            )
        return SuccessResponse(
            message="API key revoked.",
            status_code=status.HTTP_200_OK,
        )
