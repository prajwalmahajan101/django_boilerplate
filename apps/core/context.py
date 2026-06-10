"""Request context — request-ID tracking via ``ContextVar``.

Single source of truth for the current request's correlation ID. The ID is
set by :class:`core.middleware.request_id.RequestIDMiddleware` at the start
of each request and read by:

* :class:`core.utils.logging.RequestContextFilter` (logging filter that
  stamps every log record with ``request_id``),
* :class:`core.base.exception.BaseCustomError` (captures the ID at raise
  time so the response envelope can echo it back),
* Celery tasks dispatched mid-request (via :mod:`core.tasks`),
* The api_log writer.

``ContextVar`` is copied onto each new ``asyncio.Task`` and each gthread
worker thread inherits its own copy, so concurrent requests cannot bleed
IDs into one another.

The public API mirrors :mod:`contextvars` but pins the variable name and
default value so callers don't redefine the slot.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_context(request_id: str | None) -> Token[str | None]:
    """Bind a request ID to the current context.

    Returns a token that can later be passed to
    :func:`clear_request_context` to restore the prior value — important
    when nesting (e.g. a Celery task chained from inside a request).
    """
    return request_id_ctx.set(request_id)


def clear_request_context(token: Token[str | None] | None = None) -> None:
    """Reset the request ID.

    When ``token`` is provided, restores the value the context held before
    the matching :func:`set_request_context` call. When omitted, clears
    the slot to ``None`` (fallback for callers that didn't capture a
    token — the historical behaviour the boilerplate shipped with).
    """
    if token is not None:
        request_id_ctx.reset(token)
    else:
        request_id_ctx.set(None)


def get_request_id() -> str | None:
    """Read the request ID bound to the current context (``None`` if unset)."""
    return request_id_ctx.get(None)


__all__ = [
    "clear_request_context",
    "get_request_id",
    "request_id_ctx",
    "set_request_context",
]
