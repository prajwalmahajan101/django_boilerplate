"""OpenAPI metadata catalog — centralized tags, descriptions, and response envelopes.

Re-exports the public knobs from :mod:`core.openapi.metadata` so callers
can ``from core.openapi import DEFAULT_RESPONSES`` rather than reach into
the implementation module.
"""

from core.openapi.metadata import (
    API_DESCRIPTION,
    DEFAULT_RESPONSES,
    RESPONSES_BAD_GATEWAY,
    RESPONSES_BAD_REQUEST,
    RESPONSES_FORBIDDEN,
    RESPONSES_INTERNAL_SERVER_ERROR,
    RESPONSES_NOT_FOUND,
    RESPONSES_RATE_LIMITED,
    RESPONSES_SERVICE_UNAVAILABLE,
    RESPONSES_UNAUTHORIZED,
    RESPONSES_VALIDATION,
    TAGS_METADATA,
    ErrorEnvelopeSerializer,
)

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
