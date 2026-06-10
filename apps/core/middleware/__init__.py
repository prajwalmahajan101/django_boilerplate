"""Boilerplate-owned middleware.

The kit-owned middleware (``SelectiveCors``, ``SecurityHeaders``,
``BodyLimit``, ``RequestId``, ``ExceptionLogging``, ``RateLimitHeaders``)
now live in :mod:`resilience_kit.adapters.django.middleware`. What
stays here is the boilerplate-specific shell.
"""

from core.middleware.bind_request_id import BindRequestIdMiddleware
from core.middleware.request_logging import RequestLoggingMiddleware

__all__ = ["BindRequestIdMiddleware", "RequestLoggingMiddleware"]
