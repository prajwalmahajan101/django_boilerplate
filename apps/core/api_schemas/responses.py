"""Pre-built ``OpenApiResponse`` objects for every status code endpoints share.

These are the canned response variants documented at every endpoint —
404 / 422 / 401 / 403 / 429 / 502 / 503. Endpoint-specific 200 / 201
responses are constructed inline at the view; only the cross-cutting
error / throttle responses live here.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiExample, OpenApiResponse

from core.api_schemas.envelope import error_envelope, error_example

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
# request because a hard dependency (PostgreSQL, the Valkey cache, an
# upstream identity provider) is unreachable. Distinct from 502 in intent:
# 502 means a downstream we orchestrate is broken; 503 means *we* are not
# ready.
service_unavailable_response = OpenApiResponse(
    description=(
        "Service is temporarily unavailable — typically because a primary "
        "datastore (PostgreSQL or the cache) is unreachable. Retry with backoff."
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
