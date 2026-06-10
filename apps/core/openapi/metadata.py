"""Centralized OpenAPI metadata — API description, tags, and error envelopes.

Replaces the inline ``SPECTACULAR_SETTINGS['DESCRIPTION']`` /
``['TAGS']`` blobs in ``config/settings/base.py`` and the ad-hoc
``@extend_schema(responses={401: ...})`` decorators scattered across
views. All routes opt into a consistent set of error responses by
spreading :data:`DEFAULT_RESPONSES` (or one of the more specific
``RESPONSES_*`` dicts) into their ``@extend_schema(responses=...)``.

Conventions:

* ``ErrorEnvelopeSerializer`` mirrors the runtime envelope produced by
  ``core.exceptions.handler.api_exception_handler``. Keep them in sync
  — the test ``test_error_envelope.py`` is the regression guard.
* ``RESPONSES_*`` dicts map HTTP status integers to
  :class:`drf_spectacular.utils.OpenApiResponse` objects so the Swagger
  UI shows a typed example body per status, not "no description".
* :data:`DEFAULT_RESPONSES` is the cross-cutting set every authenticated
  JSON endpoint should declare (400, 401, 403, 429, 500). Endpoints that
  hit data may also spread :data:`RESPONSES_NOT_FOUND` /
  :data:`RESPONSES_VALIDATION` for richer docs.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiExample, OpenApiResponse
from rest_framework import serializers

# --------------------------------------------------------------------------
# Top-level catalog
# --------------------------------------------------------------------------

API_DESCRIPTION = (
    "Project API built on the django_boilerplate scaffold. Replace this "
    "description in :data:`core.openapi.metadata.API_DESCRIPTION` with one "
    "specific to your service.\n\n"
    "## Authentication\n\n"
    "- **Bearer JWT** — `POST /api/auth/login/` (or OAuth provider). "
    "Pass as `Authorization: Bearer <token>`.\n"
    "- **API Key** — `POST /api/accounts/api-keys/`. "
    "Pass as `X-API-Key: <key>`.\n\n"
    "## Response Envelope\n\n"
    "All responses share a common JSON envelope: `success`, `message`, "
    "`data`, `errors`, `request_id`. Paginated list endpoints wrap items "
    "under `data.items` with a `data.pagination` object.\n\n"
    "## Error Codes\n\n"
    "Errors are returned as `{success: false, errors: [{code, message, "
    "field, details}]}`. The `code` is UPPER_SNAKE_CASE and stable; the "
    "`message` is human-readable and may change between versions. Common "
    "codes:\n\n"
    "| Code | Meaning |\n"
    "| --- | --- |\n"
    "| `AUTHENTICATION_FAILED` | Credentials missing or invalid (401). |\n"
    "| `TOKEN_EXPIRED` | JWT `exp` elapsed — refresh and retry (401). |\n"
    "| `PERMISSION_DENIED` | Authenticated but lacking RBAC permission (403). |\n"
    "| `ENTITY_NOT_FOUND` | Requested row does not exist (404). |\n"
    "| `VALIDATION_ERROR` | Semantic / business-rule validation failed (400). |\n"
    "| `RATE_LIMITED` | Throttle bucket exhausted (429). |\n"
    "| `API_ERROR` | Outbound HTTP call failed (502). |\n"
    "| `SERVICE_UNAVAILABLE` | Circuit breaker open (503). |\n\n"
    "## Request Correlation\n\n"
    "Every response carries a `request_id` (also surfaced in the "
    "`X-Request-ID` response header). Clients may send their own "
    "`X-Request-ID` header to thread their trace through this service.\n"
)


TAGS_METADATA = [
    {"name": "System", "description": "Health and readiness probes. No auth required."},
    {"name": "Auth", "description": "Login, JWT token refresh, logout, and current-user profile."},
    {"name": "API Keys", "description": "Issue, list, and revoke service-account API keys."},
]


# --------------------------------------------------------------------------
# Envelope serializers (for OpenAPI documentation only — runtime envelope
# is produced by ``core.exceptions.handler.api_exception_handler``).
# --------------------------------------------------------------------------


class _ErrorItemSerializer(serializers.Serializer):
    """One ``errors[]`` entry as produced by the central exception handler."""

    code = serializers.CharField(help_text="Stable machine-readable error code.")
    message = serializers.CharField(help_text="Human-readable description.")
    field = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Dotted-path identifier of the offending field, if any.",
    )
    details = serializers.DictField(
        required=False,
        allow_null=True,
        help_text="Structured error context. Shape depends on `code`.",
    )


class ErrorEnvelopeSerializer(serializers.Serializer):
    """Standard error response envelope. See ``docs/exceptions.md``."""

    success = serializers.BooleanField(default=False)
    message = serializers.CharField()
    data = serializers.JSONField(allow_null=True, default=None)
    errors = _ErrorItemSerializer(many=True)
    request_id = serializers.CharField(allow_null=True, required=False)


# --------------------------------------------------------------------------
# Per-status response dicts. Each entry is the format drf-spectacular
# expects in ``@extend_schema(responses=...)``: an int status mapped to
# an ``OpenApiResponse`` carrying the envelope serializer and an example.
# --------------------------------------------------------------------------


def _envelope_example(code: str, message: str, *, field: str | None = None) -> OpenApiExample:
    return OpenApiExample(
        name=code,
        value={
            "success": False,
            "message": message,
            "data": None,
            "errors": [{"code": code, "message": message, "field": field, "details": None}],
            "request_id": "550e8400-e29b-41d4-a716-446655440000",
        },
        response_only=True,
    )


def _err(status: int, code: str, message: str, *, field: str | None = None) -> dict:
    return {
        status: OpenApiResponse(
            response=ErrorEnvelopeSerializer,
            description=message,
            examples=[_envelope_example(code, message, field=field)],
        )
    }


RESPONSES_BAD_REQUEST = _err(400, "BAD_REQUEST", "Malformed request.")
RESPONSES_VALIDATION = _err(400, "VALIDATION_ERROR", "Semantic validation failed.", field="amount")
RESPONSES_UNAUTHORIZED = _err(401, "AUTHENTICATION_FAILED", "Authentication required.")
RESPONSES_FORBIDDEN = _err(403, "PERMISSION_DENIED", "Permission denied.")
RESPONSES_NOT_FOUND = _err(404, "ENTITY_NOT_FOUND", "Requested resource was not found.")
RESPONSES_RATE_LIMITED = _err(429, "RATE_LIMITED", "Rate limit exceeded.")
RESPONSES_INTERNAL_SERVER_ERROR = _err(
    500, "INTERNAL_SERVER_ERROR", "An unexpected error occurred."
)
RESPONSES_BAD_GATEWAY = _err(502, "API_ERROR", "Upstream service returned an error.")
RESPONSES_SERVICE_UNAVAILABLE = _err(
    503, "SERVICE_UNAVAILABLE", "Service is currently unavailable."
)


# Cross-cutting set every authenticated JSON endpoint should declare.
# Spread into ``@extend_schema(responses={**DEFAULT_RESPONSES, 200: MySerializer})``.
DEFAULT_RESPONSES: dict = {
    **RESPONSES_BAD_REQUEST,
    **RESPONSES_UNAUTHORIZED,
    **RESPONSES_FORBIDDEN,
    **RESPONSES_RATE_LIMITED,
    **RESPONSES_INTERNAL_SERVER_ERROR,
}


__all__ = [
    "API_DESCRIPTION",
    "DEFAULT_RESPONSES",
    "RESPONSES_BAD_GATEWAY",
    "RESPONSES_BAD_REQUEST",
    "RESPONSES_FORBIDDEN",
    "RESPONSES_INTERNAL_SERVER_ERROR",
    "RESPONSES_NOT_FOUND",
    "RESPONSES_RATE_LIMITED",
    "RESPONSES_SERVICE_UNAVAILABLE",
    "RESPONSES_UNAUTHORIZED",
    "RESPONSES_VALIDATION",
    "TAGS_METADATA",
    "ErrorEnvelopeSerializer",
]
