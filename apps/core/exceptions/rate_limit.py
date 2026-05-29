"""Rate-limit exception — surfaces throttle rejections through the standard envelope.

Raised in place of DRF's ``Throttled`` (or a raw 429 response) by code paths
that want the standard ``{"success": False, "errors": [...]}`` envelope plus
the matching ``Retry-After`` / ``X-RateLimit-*`` headers.

The headers are emitted by ``RateLimitHeadersMiddleware`` (already wired in
``core.middleware``) which calls :meth:`RateLimitError.response_headers`
when the response has a corresponding ``RateLimitError`` attached.
"""

from __future__ import annotations

from typing import Any

from core.base.exception import BaseCustomError


class RateLimitError(BaseCustomError):
    """Caller exceeded the configured rate limit for the route / scope.

    Carries the throttle decision so the central handler can:
      * emit ``Retry-After`` and ``X-RateLimit-*`` headers, and
      * expose ``limit`` / ``window_seconds`` / ``retry_after`` /
        ``remaining`` / ``reset_at`` under ``errors[0].details``.
    """

    default_message = "Rate limit exceeded."
    error_code = "RATE_LIMITED"
    status_code = 429

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: int,
        retry_after: int,
        remaining: int = 0,
        reset_at: int = 0,
        message: str | None = None,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.retry_after = max(1, int(retry_after))
        self.remaining = remaining
        self.reset_at = reset_at
        super().__init__(message or f"Rate limit exceeded ({limit}/{window_seconds}s).")

    def get_details(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "window_seconds": self.window_seconds,
            "retry_after": self.retry_after,
            "remaining": self.remaining,
            "reset_at": self.reset_at,
        }

    def response_headers(self) -> dict[str, str]:
        return {
            "Retry-After": str(self.retry_after),
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Reset": str(self.reset_at),
        }


__all__ = ["RateLimitError"]
