"""``ContentLengthLimitMiddleware`` — 413 inbound bodies past a configured cap.

Two enforcement paths, both returning the project's standard error
envelope (matching the shape of every other 4xx/5xx response) instead
of Django's default HTML traceback:

1. **Declared ``Content-Length`` too large** → short-circuit before the
   request body is ever read. The common case for well-behaved clients.
2. **Streamed body exceeds Django's ``DATA_UPLOAD_MAX_MEMORY_SIZE``** →
   Django raises :class:`RequestDataTooBig` lazily when ``request.body``
   / ``request.POST`` is first accessed (typically inside the DRF
   parser). The ``process_exception`` hook below converts that to the
   same 413 envelope so the response shape is uniform.

Wired before ``RequestLoggingMiddleware`` so a rejected oversize body
short-circuits the request entirely — the access-log decorator never
reads the (potentially huge) body into memory.

Cap is read from ``MAX_REQUEST_BODY_BYTES`` (default 2 MiB). Setting
the value to ``0`` disables the middleware (declared-length check is
skipped; ``RequestDataTooBig`` from Django's own limiter still passes
through). The middleware does not alter ``DATA_UPLOAD_MAX_MEMORY_SIZE``
itself; configure that separately if a different streaming cap is
required.
"""

from __future__ import annotations

from collections.abc import Callable

from core.utils.logging import _request_id_var
from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.http import HttpRequest, HttpResponse, JsonResponse

_DEFAULT_MAX_BYTES = 2 * 1024 * 1024


def _envelope(max_bytes: int) -> JsonResponse:
    """Build the standard 413 envelope payload.

    Mirrors :class:`core.responses.error.ErrorResponse` shape directly
    via ``JsonResponse`` because DRF's renderer pipeline is not
    available at the middleware layer.
    """
    payload = {
        "success": False,
        "message": "Request body exceeds the configured size limit.",
        "data": None,
        "errors": [
            {
                "code": "REQUEST_BODY_TOO_LARGE",
                "message": (f"Request body exceeds the configured maximum of {max_bytes} bytes."),
                "field": None,
                "details": {"max_bytes": max_bytes},
            }
        ],
        "request_id": _request_id_var.get(None),
    }
    return JsonResponse(payload, status=413)


class ContentLengthLimitMiddleware:
    """Reject requests whose body exceeds ``MAX_REQUEST_BODY_BYTES``."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self.max_bytes = int(getattr(settings, "MAX_REQUEST_BODY_BYTES", _DEFAULT_MAX_BYTES))

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if self.max_bytes > 0:
            declared = self._declared_content_length(request)
            if declared is not None and declared > self.max_bytes:
                return _envelope(self.max_bytes)
        return self.get_response(request)

    def process_exception(self, request: HttpRequest, exception: Exception) -> HttpResponse | None:
        """Convert Django's lazy streaming-cap exception to the envelope."""
        if isinstance(exception, RequestDataTooBig):
            return _envelope(self.max_bytes)
        return None

    @staticmethod
    def _declared_content_length(request: HttpRequest) -> int | None:
        raw = request.META.get("CONTENT_LENGTH")
        if not raw:
            return None
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None


__all__ = ["ContentLengthLimitMiddleware"]
