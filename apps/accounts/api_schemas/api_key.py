"""OpenAPI schemas for the DELETE / POST API-key state-transition endpoints."""

from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema

from accounts.api_schemas._common import (
    _auth_required_schema,
    _error_response_schema,
)
from core.api_schemas import throttle_response

api_key_delete_schema = extend_schema(
    operation_id="api_keys_delete",
    summary="Delete an API key",
    description=(
        "Soft-deletes an API key by setting ``is_active=False``. The row "
        "is retained for audit; the raw key bytes were never persisted "
        "(only an HMAC-comparable encrypted form), so the credential is "
        "irrecoverable once revoked.\n\n"
        "**Idempotent:** revoking an already-revoked key is a no-op and "
        "still returns ``204``.\n\n"
        "**Authentication:** Bearer JWT required.\n"
        "**RBAC:** ``API_KEY:DELETE``."
    ),
    tags=["API Keys"],
    responses={
        204: OpenApiResponse(description="API key soft-deleted (no body)."),
        401: OpenApiResponse(
            description="Authentication credentials missing or invalid.",
            response=_auth_required_schema,
            examples=[
                OpenApiExample(
                    name="unauthorized",
                    value={"detail": "Authentication credentials were not provided."},
                ),
            ],
        ),
        403: OpenApiResponse(
            description="The authenticated user lacks ``API_KEY:DELETE``.",
            response=_auth_required_schema,
            examples=[
                OpenApiExample(
                    name="forbidden",
                    value={"detail": "You do not have permission to perform this action."},
                ),
            ],
        ),
        404: OpenApiResponse(
            description="API key not found (or already soft-deleted by another caller).",
            response=_error_response_schema,
            examples=[
                OpenApiExample(
                    name="not_found",
                    value={"success": False, "message": "API key not found."},
                ),
            ],
        ),
        429: throttle_response,
    },
)


api_key_revoke_schema = extend_schema(
    operation_id="api_keys_revoke",
    summary="Revoke an API key",
    description=(
        "Soft-revokes an API key by stamping ``revoked_at``. The row stays "
        "around with ``is_active=True`` (distinct from delete) so the audit "
        "trail is preserved, but ``APIKeyAuthentication`` returns ``401`` on "
        "the next request that presents the key.\n\n"
        "**Idempotent:** revoking an already-revoked key returns ``200`` "
        "with a message indicating no state change.\n\n"
        "**Authentication:** Bearer JWT required.\n"
        "**RBAC:** ``API_KEY:UPDATE``."
    ),
    tags=["API Keys"],
    request=None,
    responses={
        200: OpenApiResponse(
            description=(
                "API key revoked. Two payload shapes share this status: a "
                "fresh revocation (``API key revoked.``) or an idempotent "
                "no-op when the key was already revoked "
                "(``API key already revoked.``)."
            ),
            examples=[
                OpenApiExample(
                    name="revoked",
                    value={"success": True, "message": "API key revoked."},
                ),
                OpenApiExample(
                    name="already_revoked",
                    value={"success": True, "message": "API key already revoked."},
                ),
            ],
        ),
        401: OpenApiResponse(
            description="Authentication credentials missing or invalid.",
            response=_auth_required_schema,
            examples=[
                OpenApiExample(
                    name="unauthorized",
                    value={"detail": "Authentication credentials were not provided."},
                ),
            ],
        ),
        403: OpenApiResponse(
            description="The authenticated user lacks ``API_KEY:UPDATE``.",
            response=_auth_required_schema,
            examples=[
                OpenApiExample(
                    name="forbidden",
                    value={"detail": "You do not have permission to perform this action."},
                ),
            ],
        ),
        404: OpenApiResponse(
            description=(
                "No active API key with that ``pk``. Soft-deleted keys "
                "(``is_active=False``) are NOT revivable through this endpoint."
            ),
            response=_error_response_schema,
            examples=[
                OpenApiExample(
                    name="not_found",
                    value={"success": False, "message": "API key not found."},
                ),
            ],
        ),
        429: throttle_response,
    },
)
