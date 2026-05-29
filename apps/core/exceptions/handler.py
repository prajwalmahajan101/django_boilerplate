"""Custom DRF exception handler that wraps errors in the standard envelope."""

from __future__ import annotations

from threading import Lock
from typing import Any

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from core.base.exception import BaseCustomError, derive_error_code
from core.exceptions.infrastructure import (
    ExternalServiceError,
    ExternalTimeoutError,
    S3Exception,
    SESException,
    ServiceUnavailableError,
)
from core.exceptions.repository import (
    EntityNotFoundError,
    InactiveParentError,
    InvalidInputError,
    InvalidOutboundURLError,
    RepositoryError,
)
from core.utils.logging import _request_id_var

# Map custom exception types to HTTP status codes.
# The builder list is the source of truth; the tuple is a lazily-built
# cache, invalidated whenever register_exception_mapping() is called.
# All read/append/snapshot transitions on these globals run under
# _status_map_lock so late, possibly-cross-thread registrations cannot
# observe a partially-built tuple.
_CUSTOM_STATUS_MAP_BUILDER: list[tuple[type[BaseCustomError], int]] = []
_CUSTOM_STATUS_MAP: tuple[tuple[type[BaseCustomError], int], ...] | None = None
_status_map_lock = Lock()


def _drf_error_code(exc: Exception) -> str:
    """Derive UPPER_SNAKE_CASE error code from a DRF exception class name.

    DRF class names like ``NotAuthenticated`` don't carry an ``Error``
    suffix, so strip_suffix=False preserves the full name.
    """
    return derive_error_code(type(exc).__name__, strip_suffix=False)


def _build_error_dict(
    code: str,
    message: str,
    *,
    field: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {"code": code, "message": message, "field": field, "details": details}


def _get_status_map() -> tuple[tuple[type[BaseCustomError], int], ...]:
    """Return the cached exception-to-status map, rebuilding if invalidated."""
    global _CUSTOM_STATUS_MAP
    # Fast path: warm cache, no lock acquisition.
    cached = _CUSTOM_STATUS_MAP
    if cached is not None:
        return cached
    # Slow path: take the lock and rebuild under double-checked locking
    # so concurrent first-callers cannot snapshot the builder mid-append.
    with _status_map_lock:
        if _CUSTOM_STATUS_MAP is None:
            _CUSTOM_STATUS_MAP = tuple(_CUSTOM_STATUS_MAP_BUILDER)
        return _CUSTOM_STATUS_MAP


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Reshape DRF exceptions into the standard envelope."""

    # Handle project-level custom exceptions first.
    if isinstance(exc, BaseCustomError):
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        # Allow per-instance status_code override (set via BaseCustomError(..., status_code=...))
        if hasattr(exc, "status_code"):
            status_code = exc.status_code
        else:
            for exc_class, code in _get_status_map():
                if isinstance(exc, exc_class):
                    status_code = code
                    break

        request_id = getattr(exc, "request_id", None) or _request_id_var.get(None)

        return Response(
            {
                "success": False,
                "message": str(exc),
                "data": None,
                "errors": [exc.to_error_dict()],
                "request_id": request_id,
            },
            status=status_code,
        )

    # Fall back to DRF's built-in exception handling.
    response = exception_handler(exc, context)

    if response is None:
        # Non-DRF exception that DRF can't reshape. Without this branch
        # Django would render its default 500 HTML page, breaking the
        # envelope contract. ExceptionLoggingMiddleware has already
        # logged the original with exc_info, so observability is intact.
        request_id = _request_id_var.get(None)
        return Response(
            {
                "success": False,
                "message": "An unexpected error occurred.",
                "data": None,
                "errors": [
                    _build_error_dict(
                        "INTERNAL_SERVER_ERROR",
                        "An unexpected error occurred.",
                    )
                ],
                "request_id": request_id,
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    error_code = _drf_error_code(exc)
    errors: list[dict[str, Any]]

    if isinstance(response.data, dict):
        detail = response.data.pop("detail", None)
        remaining_errors = response.data if response.data else None
        message = str(detail) if detail else "Validation failed"

        if remaining_errors:
            errors = []
            for field, msgs in remaining_errors.items():
                if isinstance(msgs, list):
                    for msg in msgs:
                        errors.append(
                            _build_error_dict("VALIDATION_ERROR", str(msg), field=field)
                        )
                else:
                    errors.append(
                        _build_error_dict("VALIDATION_ERROR", str(msgs), field=field)
                    )
        else:
            errors = [_build_error_dict(error_code, message)]
    elif isinstance(response.data, list):
        message = "; ".join(str(e) for e in response.data)
        errors = [_build_error_dict(error_code, str(e)) for e in response.data]
    else:
        message = str(response.data)
        errors = [_build_error_dict(error_code, message)]

    request_id = getattr(exc, "request_id", None) or _request_id_var.get(None)

    response.data = {
        "success": False,
        "message": message,
        "data": None,
        "errors": errors,
        "request_id": request_id,
    }

    return response


def register_exception_mapping(
    exc_class: type[BaseCustomError],
    status_code: int,
) -> None:
    """Register a custom exception to HTTP status code mapping.

    Mappings are checked in registration order with ``isinstance()``,
    so register more specific exception classes before their parents.

    Safe to call from ``AppConfig.ready()`` even after the handler has
    already run once: the cached frozen tuple is invalidated here and
    rebuilt on the next ``_get_status_map()`` call. Append + invalidate
    happen under ``_status_map_lock`` so a concurrent reader either sees
    the prior tuple in full or rebuilds with the new entry included —
    never a partial snapshot.
    """
    global _CUSTOM_STATUS_MAP
    with _status_map_lock:
        _CUSTOM_STATUS_MAP_BUILDER.append((exc_class, status_code))
        _CUSTOM_STATUS_MAP = None  # invalidate cache — rebuilt on next use


# Self-register core exception mappings (specific → general).
register_exception_mapping(EntityNotFoundError, status.HTTP_404_NOT_FOUND)
register_exception_mapping(ServiceUnavailableError, status.HTTP_503_SERVICE_UNAVAILABLE)
register_exception_mapping(ExternalTimeoutError, status.HTTP_502_BAD_GATEWAY)
register_exception_mapping(S3Exception, status.HTTP_502_BAD_GATEWAY)
register_exception_mapping(SESException, status.HTTP_502_BAD_GATEWAY)
register_exception_mapping(ExternalServiceError, status.HTTP_502_BAD_GATEWAY)  # parent class — must be last
register_exception_mapping(InactiveParentError, status.HTTP_409_CONFLICT)
register_exception_mapping(InvalidOutboundURLError, status.HTTP_400_BAD_REQUEST)
register_exception_mapping(InvalidInputError, status.HTTP_400_BAD_REQUEST)

# The map is cached lazily on first call to _get_status_map(). Any later
# register_exception_mapping() invalidates the cache, so domain apps can
# safely register at any point (typically in AppConfig.ready()) and the
# new mapping is picked up on the next handler invocation.
