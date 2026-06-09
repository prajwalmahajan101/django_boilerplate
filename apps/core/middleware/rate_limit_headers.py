"""Middleware to add rate limit headers to responses."""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse


class RateLimitHeadersMiddleware:
    """Middleware to add rate limit headers to responses.

    Adds standard rate limit headers to all API responses:
    - X-RateLimit-Limit: Maximum requests allowed in current window
    - X-RateLimit-Remaining: Requests remaining in current window
    - X-RateLimit-Reset: Unix timestamp when limit resets
    """

    def __init__(self, get_response: Callable):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        from django.conf import settings as django_settings

        response = self.get_response(request)

        if not django_settings.RATE_LIMIT_CONFIG.get("ENABLE_HEADERS", True):
            return response

        if hasattr(request, "_throttle_limit"):
            response["X-RateLimit-Limit"] = str(request._throttle_limit)
        if hasattr(request, "_throttle_remaining"):
            response["X-RateLimit-Remaining"] = str(request._throttle_remaining)
        if hasattr(request, "_throttle_reset"):
            response["X-RateLimit-Reset"] = str(request._throttle_reset)

        return response
