"""Middleware for request/response logging."""

import logging
import time
from typing import Callable

from django.http import HttpRequest, HttpResponse

from core.utils.log_sanitization import safe_log_dict, truncate_for_log

logger = logging.getLogger(__name__)


def get_user_id(request: HttpRequest) -> int | None:
    """Return the authenticated user's ID, or None for anonymous users."""
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return user.pk
    return None


class RequestLoggingMiddleware:
    """Middleware to log all incoming requests and responses."""

    def __init__(self, get_response: Callable):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        start_time = time.time()

        logger.info(
            "Incoming request",
            extra=safe_log_dict(
                method=request.method,
                path=truncate_for_log(request.path, max_length=200),
                user_id=get_user_id(request),
                remote_addr=self._get_client_ip(request),
            ),
        )

        response = self.get_response(request)

        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            "Request completed",
            extra=safe_log_dict(
                method=request.method,
                path=truncate_for_log(request.path, max_length=200),
                user_id=get_user_id(request),
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
            ),
        )

        return response

    def _get_client_ip(self, request: HttpRequest) -> str:
        """Extract client IP from request.

        Only trusts X-Forwarded-For when USE_X_FORWARDED_FOR is enabled.
        """
        from django.conf import settings

        if getattr(settings, "USE_X_FORWARDED_FOR", False):
            x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
            if x_forwarded_for:
                return x_forwarded_for.split(",")[0].strip()

        return request.META.get("REMOTE_ADDR", "unknown")
