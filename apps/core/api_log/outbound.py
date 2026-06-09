"""``@log_outbound`` — audit decorator for service methods calling http_client.

Wraps a service method that issues an outbound HTTP call. The
decorator inspects the returned :class:`core.utils.http_client.HttpResponse`
(or the raised exception) and emits one ``ApiLog`` row per call. The
service method's signature is unchanged.

Usage::

    @log_outbound("partner_api")
    def fetch_score(self, partner_id: int, payload: dict) -> HttpResponse:
        return make_http_request(
            "POST",
            "https://partner.example.com/score",
            json_body=payload,
        )
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from core.api_log.dispatch import capture_and_dispatch
from core.api_log.error_messages import build_error_message
from core.api_log.models import Direction
from core.api_log.sanitizers import redact_headers, serialize_body
from core.utils.logging import _request_id_var


def log_outbound(service_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate a service method to emit one ``ApiLog`` row per outbound call."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            def build_row(result: Any, exc: BaseException | None, elapsed_ms: float) -> dict:
                url = ""
                method = ""
                status_code = None
                response_body: str | None = None
                response_headers: dict[str, str] = {}
                request_headers: dict[str, str] = {}
                request_body: str | None = None
                error: dict | None = None

                request_ctx = getattr(result, "request", None) if exc is None else None
                if isinstance(request_ctx, dict):
                    url = str(request_ctx.get("url") or "")
                    method = str(request_ctx.get("method") or "")
                    hdrs = request_ctx.get("headers")
                    if isinstance(hdrs, dict):
                        request_headers = hdrs
                    request_body = serialize_body(request_ctx.get("body"))

                if exc is not None:
                    error = {
                        "type": type(exc).__name__,
                        "message": build_error_message(exc),
                    }
                else:
                    status_code = getattr(result, "status_code", None)
                    response_body = serialize_body(getattr(result, "body", None))
                    headers = getattr(result, "headers", None)
                    if isinstance(headers, dict):
                        response_headers = headers

                return {
                    "direction": Direction.OUTBOUND,
                    "service_name": service_name,
                    "request_id": _request_id_var.get(None) or "",
                    "method": method,
                    "url": url,
                    "status_code": status_code,
                    "duration_ms": elapsed_ms,
                    "request_headers": redact_headers(request_headers),
                    "request_body": request_body,
                    "response_headers": redact_headers(response_headers),
                    "response_body": response_body,
                    "error": error,
                    "extra": {},
                }

            return capture_and_dispatch(
                fn,
                args,
                kwargs,
                build_row,
                service_name=service_name,
                direction=Direction.OUTBOUND,
            )

        return wrapper

    return decorator


__all__ = ["log_outbound"]
