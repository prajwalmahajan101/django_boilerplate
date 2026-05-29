"""``@log_inbound`` — audit decorator for DRF view methods.

Reads the request body once (Django parses lazily), captures the
response status + body, and dispatches the audit row through
:func:`core.api_log.dispatch.capture_and_dispatch`. The decorator
introduces zero behaviour change on the request path — result or
exception are returned/re-raised exactly as the wrapped view emitted
them.

Usage::

    @log_inbound("public_api")
    def post(self, request, *args, **kwargs):
        ...
"""

from __future__ import annotations

import functools
from typing import Any, Callable

from core.api_log.dispatch import capture_and_dispatch
from core.api_log.models import Direction
from core.api_log.sanitizers import redact_headers, serialize_body
from core.utils.logging import _request_id_var


def _request_from_args(args: tuple, kwargs: dict) -> Any:
    """Locate the HttpRequest / DRF Request in the view's args."""
    if "request" in kwargs:
        return kwargs["request"]
    for a in args:
        if hasattr(a, "META") and hasattr(a, "method"):
            return a
    return None


def _request_headers(request: Any) -> dict[str, str]:
    if not request:
        return {}
    try:
        return {k: v for k, v in request.headers.items()}
    except Exception:
        return {}


def log_inbound(service_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate a DRF view method to emit one ``ApiLog`` row per call."""

    def decorator(view: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(view)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = _request_from_args(args, kwargs)

            def build_row(result: Any, exc: BaseException | None, elapsed_ms: float) -> dict:
                status_code = None
                response_body: str | None = None
                response_headers: dict[str, str] = {}
                error: dict | None = None
                if exc is not None:
                    error = {"type": type(exc).__name__, "message": str(exc)}
                else:
                    status_code = getattr(result, "status_code", None)
                    response_body = serialize_body(getattr(result, "data", None))
                    try:
                        response_headers = {k: v for k, v in result.headers.items()}
                    except Exception:
                        response_headers = {}

                request_body: str | None = None
                if request is not None:
                    try:
                        body = request.body
                    except Exception:
                        body = None
                    request_body = serialize_body(body)

                return {
                    "direction": Direction.INBOUND,
                    "service_name": service_name,
                    "request_id": _request_id_var.get(None) or "",
                    "method": getattr(request, "method", "") or "",
                    "url": getattr(request, "path", "") or "",
                    "status_code": status_code,
                    "duration_ms": elapsed_ms,
                    "request_headers": redact_headers(_request_headers(request)),
                    "request_body": request_body,
                    "response_headers": redact_headers(response_headers),
                    "response_body": response_body,
                    "error": error,
                    "extra": {},
                }

            return capture_and_dispatch(view, args, kwargs, build_row)

        return wrapper

    return decorator


__all__ = ["log_inbound"]
