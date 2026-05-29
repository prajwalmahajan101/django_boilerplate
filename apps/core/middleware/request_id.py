"""Middleware for request ID tracking."""

import re
import uuid
from typing import Callable

from django.http import HttpRequest, HttpResponse

from core.utils.logging import clear_request_context, set_request_context

# Valid request ID: UUID format or alphanumeric with hyphens, max 128 chars
_REQUEST_ID_PATTERN = re.compile(r"^[a-zA-Z0-9\-]{1,128}$")


class RequestIDMiddleware:
    """Middleware to extract or generate request ID for tracing.

    Checks for X-Request-ID header, generates UUID if not present.
    Adds request_id to request object and response headers.
    """

    def __init__(self, get_response: Callable):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        provided_id = request.headers.get("X-Request-ID")
        if provided_id and _REQUEST_ID_PATTERN.match(provided_id):
            request_id = provided_id
        else:
            request_id = str(uuid.uuid4())

        request.request_id = request_id

        set_request_context(request_id=request_id)

        try:
            response = self.get_response(request)
            response["X-Request-ID"] = request_id
            return response
        finally:
            clear_request_context()
