"""``APIError`` — raised by outbound HTTP clients on non-2xx / transport failures.

Kept separate from ``ExternalServiceError`` (the resilience-layer abstract
parent) so consumers that only care about HTTP-level details (status, body)
can catch it directly without pulling in the broader hierarchy.
"""

from __future__ import annotations

from typing import Any

from core.base.exception import BaseCustomError


class APIError(BaseCustomError):
    """Outbound HTTP call failed with a non-2xx status or transport error."""

    default_message = "HTTP request failed."
    error_code = "API_ERROR"
    status_code = 502

    def __init__(
        self,
        message: str | None = None,
        *,
        status_code: int | None = None,
        response_body: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)
        self.response_body = response_body
        self.details = details or {}

    def get_details(self) -> dict[str, Any]:
        out: dict[str, Any] = {**(self.details or {})}
        if self.response_body is not None:
            out["response_body"] = self.response_body
        if self.status_code is not None:
            out["status_code"] = self.status_code
        return out
