"""Middleware for exception logging with request context."""

import logging
from typing import Callable

from django.http import HttpRequest, HttpResponse
from rest_framework.exceptions import APIException

from core.middleware.request_logging import get_user_id
from core.utils.log_sanitization import safe_log_dict, truncate_for_log

logger = logging.getLogger(__name__)


class ExceptionLoggingMiddleware:
    """Middleware to catch and log all exceptions with request context.

    DRF APIExceptions (401, 403, 404, etc.) are expected operational events
    and logged at WARNING. All other exceptions are logged at ERROR.
    Returning None continues exception propagation to the DRF handler.
    """

    def __init__(self, get_response: Callable):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

    def process_exception(self, request: HttpRequest, exception: Exception) -> None:
        """Log exception with request context."""
        log_extra = safe_log_dict(
            method=request.method,
            path=truncate_for_log(request.path, max_length=200),
            user_id=get_user_id(request),
            exception_type=type(exception).__name__,
            exception_message=truncate_for_log(str(exception), max_length=500),
        )

        if isinstance(exception, APIException):
            logger.warning("Handled API exception", extra=log_extra)
        else:
            logger.error("Unhandled exception", exc_info=True, extra=log_extra)
