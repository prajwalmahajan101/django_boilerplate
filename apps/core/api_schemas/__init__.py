"""Shared OpenAPI schema helpers.

All API responses in this project go through the standard envelope::

    {
        "success": bool,
        "message": str,
        "data": <payload> | null,
        "errors": list | null,
        "request_id": str | null,
    }

This package provides reusable helpers so drf-spectacular generates complete
response schemas (with examples) for every endpoint that uses the envelope.

Submodules:
- ``envelope`` — schema builders + example builders + pagination params
- ``responses`` — pre-built ``OpenApiResponse`` objects (404, 422, 401, 403, 429, 502, 503)
- ``system`` — health + readiness endpoint ``extend_schema`` decorators

Callers import flat names from this package
(``from core.api_schemas import throttle_response``); submodule paths are
an implementation detail.
"""

from core.api_schemas.envelope import (
    PAGINATION_PARAMETERS,
    envelope_example,
    envelope_schema,
    error_envelope,
    error_example,
    paginated_envelope_schema,
)
from core.api_schemas.responses import (
    auth_required_response,
    external_dependency_response,
    forbidden_response,
    not_found_response,
    service_unavailable_response,
    throttle_response,
    validation_error_response,
)
from core.api_schemas.system import health_schema, readiness_schema

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
