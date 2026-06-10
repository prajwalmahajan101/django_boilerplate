"""Bridge the kit's request_id ContextVar into the boilerplate's own.

Closes the M7 B1 dogfooding blocker: the kit's ``RequestIdMiddleware``
writes its UUID to :data:`resilience_kit.context.request_id`, while
:class:`BaseCustomError`, ``RequestContextFilter`` (the structured-log
formatter), and the envelope handler all read from
:data:`core.context.request_id_ctx`. Without this bridge, every
response envelope and log line emits ``"request_id": null``.

:func:`resilience_kit.context.bind_to` is a context manager that mirrors
the kit's current ``request_id`` value into a target ContextVar for the
duration of the block. Wrapping ``get_response(request)`` keeps the
boilerplate's read path correct for downstream middleware, the view,
the DRF handler, and any threadlocal-aware logging filter — without
requiring callers to reach across packages.

Slot this middleware **immediately after**
``resilience_kit.adapters.django.middleware.RequestIdMiddleware`` in
``MIDDLEWARE`` so the kit has already written its ContextVar before
the bridge mirrors it.
"""

from __future__ import annotations

from typing import Callable

from django.http import HttpRequest, HttpResponse
from resilience_kit.context import bind_to

from core.context import request_id_ctx


class BindRequestIdMiddleware:
    """Mirror ``resilience_kit.context.request_id`` → ``core.context.request_id_ctx``."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        with bind_to(request_id_ctx):
            return self.get_response(request)
