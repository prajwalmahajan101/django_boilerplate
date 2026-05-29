"""Shared OpenAPI schema helpers.

All API responses in this project go through the standard envelope::

    {
        "success": bool,
        "message": str,
        "data": <payload> | null,
        "errors": list | null,
        "request_id": str | null,
    }

This module provides reusable helpers so drf-spectacular generates complete
response schemas (with examples) for every endpoint that uses the envelope.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema

# ---------------------------------------------------------------------------
# Shared pagination parameters for list endpoints
# ---------------------------------------------------------------------------

PAGINATION_PARAMETERS = [
    OpenApiParameter(
        name="page",
        type=int,
        location=OpenApiParameter.QUERY,
        required=False,
        description="Page number (1-based). Defaults to 1.",
    ),
    OpenApiParameter(
        name="page_size",
        type=int,
        location=OpenApiParameter.QUERY,
        required=False,
        description="Number of items per page (1–100). Defaults to 20.",
    ),
]


# ---------------------------------------------------------------------------
# Envelope builders
# ---------------------------------------------------------------------------


def envelope_schema(
    data_schema: dict[str, Any] | None = None,
    *,
    success: bool = True,
    message_example: str = "Success",
) -> dict[str, Any]:
    """Wrap *data_schema* in the standard response envelope."""
    return {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "example": success},
            "message": {"type": "string", "example": message_example},
            "data": data_schema or {"type": "object", "nullable": True},
            "errors": {
                "type": "array",
                "items": {"type": "object"},
                "nullable": True,
                "example": None,
            },
            "request_id": {
                "type": "string",
                "nullable": True,
                "example": "b0f1e6c2-1a1e-4f7a-9a6a-0b0e2d2b2a9e",
            },
        },
        "required": ["success", "message"],
    }


def paginated_envelope_schema(item_schema: dict[str, Any]) -> dict[str, Any]:
    """Envelope with a paginated list payload in ``data``."""
    return envelope_schema(
        {
            "type": "object",
            "properties": {
                "items": {"type": "array", "items": item_schema},
                "pagination": {
                    "type": "object",
                    "properties": {
                        "total_count": {"type": "integer", "example": 42},
                        "page_size": {"type": "integer", "example": 20},
                        "page_number": {"type": "integer", "example": 1},
                        "total_pages": {"type": "integer", "example": 3},
                        "has_previous": {"type": "boolean", "example": False},
                        "has_next": {"type": "boolean", "example": True},
                    },
                    "required": [
                        "total_count",
                        "page_size",
                        "page_number",
                        "total_pages",
                        "has_previous",
                        "has_next",
                    ],
                },
            },
            "required": ["items", "pagination"],
        }
    )


def error_envelope(
    *, message_example: str, errors_example: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Error envelope with populated ``errors`` example."""
    return {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "example": False},
            "message": {"type": "string", "example": message_example},
            "data": {"type": "object", "nullable": True, "example": None},
            "errors": {
                "type": "array",
                "items": {"type": "object"},
                "nullable": True,
                "example": errors_example,
            },
            "request_id": {
                "type": "string",
                "nullable": True,
                "example": "b0f1e6c2-1a1e-4f7a-9a6a-0b0e2d2b2a9e",
            },
        },
        "required": ["success", "message"],
    }


# ---------------------------------------------------------------------------
# Canned responses used across multiple endpoints
# ---------------------------------------------------------------------------


def envelope_example(data: Any, message: str = "Success") -> dict[str, Any]:
    return {
        "success": True,
        "message": message,
        "data": data,
        "errors": None,
        "request_id": "b0f1e6c2-1a1e-4f7a-9a6a-0b0e2d2b2a9e",
    }


def error_example(message: str, errors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "success": False,
        "message": message,
        "data": None,
        "errors": errors,
        "request_id": "b0f1e6c2-1a1e-4f7a-9a6a-0b0e2d2b2a9e",
    }


not_found_response = OpenApiResponse(
    description="Resource not found.",
    response=error_envelope(message_example="Partner not found"),
    examples=[
        OpenApiExample(
            name="not_found",
            value=error_example("Partner not found"),
        ),
    ],
)

validation_error_response = OpenApiResponse(
    description="Request body failed validation.",
    response=error_envelope(
        message_example="Invalid input",
        errors_example=[{"field": "code", "detail": "This field is required."}],
    ),
    examples=[
        OpenApiExample(
            name="validation_error",
            value=error_example(
                "Invalid input",
                errors=[{"field": "code", "detail": "This field is required."}],
            ),
        ),
    ],
)

auth_required_response = OpenApiResponse(
    description="Authentication credentials were not provided or are invalid.",
    response={
        "type": "object",
        "properties": {
            "detail": {
                "type": "string",
                "example": "Authentication credentials were not provided.",
            },
        },
    },
    examples=[
        OpenApiExample(
            name="unauthorized",
            value={"detail": "Authentication credentials were not provided."},
        ),
    ],
)

forbidden_response = OpenApiResponse(
    description="The authenticated user lacks permission for this action.",
    response={
        "type": "object",
        "properties": {
            "detail": {
                "type": "string",
                "example": "You do not have permission to perform this action.",
            },
        },
    },
    examples=[
        OpenApiExample(
            name="forbidden",
            value={"detail": "You do not have permission to perform this action."},
        ),
    ],
)

# DRF's ``Throttled`` exception serializes as ``{"detail": "...", "retry_after": N}``
# (the second key only when the throttle reports a wait). Documenting both means
# clients can rely on ``retry_after`` for backoff without parsing the message.
throttle_response = OpenApiResponse(
    description=(
        "Rate limit exceeded. Apply exponential backoff or wait for "
        "``retry_after`` seconds before retrying. The default throttle "
        "stack (``UserTierThrottle`` + ``BurstThrottle`` + ``GlobalThrottle``) "
        "is applied to every endpoint; some endpoints add stricter throttles "
        "on top."
    ),
    response={
        "type": "object",
        "properties": {
            "detail": {
                "type": "string",
                "example": "Request was throttled. Expected available in 3600 seconds.",
            },
            "retry_after": {
                "type": "integer",
                "nullable": True,
                "example": 3600,
                "description": "Seconds until the next attempt is allowed (when reported).",
            },
        },
        "required": ["detail"],
    },
    examples=[
        OpenApiExample(
            name="throttled",
            value={
                "detail": "Request was throttled. Expected available in 3600 seconds.",
                "retry_after": 3600,
            },
        ),
    ],
)

# 502 — an external dependency this endpoint depends on returned an error,
# timed out, or is otherwise unreachable. This covers S3 (assets), partner
# APIs (push-lead), and AWS SES (email side-effects). The DB is *not* the
# source of 502; database outages surface as 503 (see below).
external_dependency_response = OpenApiResponse(
    description=(
        "An external dependency (S3, partner API, AWS SES, …) failed, "
        "timed out, or returned an unexpected status. The user-facing "
        "transaction has been rolled back where applicable. Safe to retry "
        "after a short delay."
    ),
    response=error_envelope(
        message_example="External dependency failed.",
        errors_example=[
            {
                "code": "EXTERNAL_DEPENDENCY_ERROR",
                "message": "Upstream service returned 503.",
            }
        ],
    ),
    examples=[
        OpenApiExample(
            name="s3_failure",
            value=error_example(
                "S3 service is unavailable.",
                errors=[{"code": "S3_ERROR", "message": "S3 returned 503 ServiceUnavailable."}],
            ),
        ),
        OpenApiExample(
            name="partner_api_failure",
            value=error_example(
                "Partner API returned an error.",
                errors=[
                    {
                        "code": "PARTNER_PUSH_ERROR",
                        "message": "Partner API responded with 500.",
                    }
                ],
            ),
        ),
    ],
)

# 503 — the *project's own* service is temporarily unable to serve the
# request because a hard dependency (PostgreSQL, Synoriq read replica, the
# Valkey cache) is unreachable. Distinct from 502 in intent: 502 means a
# downstream we orchestrate is broken; 503 means *we* are not ready.
service_unavailable_response = OpenApiResponse(
    description=(
        "Service is temporarily unavailable — typically because a primary "
        "datastore (PostgreSQL, Synoriq) is unreachable. Retry with backoff."
    ),
    response=error_envelope(
        message_example="Service temporarily unavailable.",
        errors_example=[
            {
                "code": "SERVICE_UNAVAILABLE",
                "message": "Database connection failed.",
            }
        ],
    ),
    examples=[
        OpenApiExample(
            name="database_unavailable",
            value=error_example(
                "Service temporarily unavailable.",
                errors=[
                    {
                        "code": "SERVICE_UNAVAILABLE",
                        "message": "Database connection failed.",
                    }
                ],
            ),
        ),
    ],
)


__all__ = [
    "PAGINATION_PARAMETERS",
    "envelope_schema",
    "paginated_envelope_schema",
    "error_envelope",
    "envelope_example",
    "error_example",
    "not_found_response",
    "validation_error_response",
    "auth_required_response",
    "forbidden_response",
    "throttle_response",
    "external_dependency_response",
    "service_unavailable_response",
    "health_schema",
    "readiness_schema",
]


# ---------------------------------------------------------------------------
# System endpoints (health, readiness)
# ---------------------------------------------------------------------------


health_schema = extend_schema(
    operation_id="system_health",
    summary="Service health check",
    description=(
        "Lightweight health probe for load balancers. Returns 200 when the "
        "database is reachable, 503 otherwise. Staff users additionally "
        "receive a ``checks`` map with component-level status."
    ),
    tags=["System"],
    responses={
        200: OpenApiResponse(
            description="Service is healthy.",
            response={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "healthy"},
                    "checks": {
                        "type": "object",
                        "nullable": True,
                        "properties": {
                            "database": {"type": "string", "example": "connected"},
                        },
                    },
                },
            },
            examples=[
                OpenApiExample(
                    name="healthy",
                    value={"status": "healthy"},
                ),
                OpenApiExample(
                    name="healthy_staff",
                    value={
                        "status": "healthy",
                        "checks": {"database": "connected"},
                    },
                    description="Response seen by staff users.",
                ),
            ],
        ),
        503: OpenApiResponse(
            description="Service is unhealthy — database unreachable.",
            response={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "unhealthy"},
                },
            },
            examples=[
                OpenApiExample(
                    name="unhealthy",
                    value={"status": "unhealthy"},
                ),
            ],
        ),
    },
)


readiness_schema = extend_schema(
    operation_id="system_readiness",
    summary="Service readiness check",
    description=(
        "Readiness probe for orchestration systems (Kubernetes, ECS). "
        "Checks database, Valkey cache, and Celery broker connectivity. "
        "Returns 200 when all dependencies are reachable, 503 otherwise. "
        "Staff users additionally receive a ``checks`` map."
    ),
    tags=["System"],
    responses={
        200: OpenApiResponse(
            description="All dependencies are reachable.",
            response={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "ready"},
                    "checks": {
                        "type": "object",
                        "nullable": True,
                        "properties": {
                            "database": {"type": "string", "example": "connected"},
                            "cache": {"type": "string", "example": "connected"},
                            "celery_broker": {"type": "string", "example": "connected"},
                        },
                    },
                },
            },
            examples=[
                OpenApiExample(
                    name="ready",
                    value={"status": "ready"},
                ),
                OpenApiExample(
                    name="ready_staff",
                    value={
                        "status": "ready",
                        "checks": {
                            "database": "connected",
                            "cache": "connected",
                            "celery_broker": "connected",
                        },
                    },
                ),
            ],
        ),
        503: OpenApiResponse(
            description="One or more dependencies are unreachable.",
            response={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "not_ready"},
                },
            },
            examples=[
                OpenApiExample(
                    name="not_ready",
                    value={"status": "not_ready"},
                ),
            ],
        ),
    },
)
