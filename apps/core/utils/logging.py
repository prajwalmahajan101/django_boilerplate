"""Common logging utilities and context management.

The request-ID slot itself lives in :mod:`core.context`; this module
re-exports it as ``_request_id_var`` for the (many) existing callers that
import it from here, plus the legacy ``set_request_context`` /
``clear_request_context`` shims that ignored tokens. New code should
import from :mod:`core.context` directly.
"""

import contextvars
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from core.context import (  # re-exported for back-compat
    clear_request_context as _clear_request_context_with_token,
)
from core.context import request_id_ctx as _request_id_var
from core.context import set_request_context as _set_request_context_with_token

# Business-identifier context variables. Populated via `domain_context(...)` at
# service-layer boundaries (push, assignment engine, remark task) so every
# nested log record — including those emitted from `make_http_request` and
# `SqlLeadsStrategy._run` — carries the same identifiers without each call
# site having to thread them through manually.
_partner_id_var: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "_partner_id_var", default=None
)
_app_number_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_app_number_var", default=None
)
_query_id_var: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "_query_id_var", default=None
)


def set_request_context(request_id: str | None = None) -> None:
    """Set request ID context for tracing across async boundaries.

    Legacy shim — discards the reset token. New code should use
    :func:`core.context.set_request_context` directly and pair the
    returned token with :func:`core.context.clear_request_context`.
    """
    if request_id is not None:
        _set_request_context_with_token(request_id)


def clear_request_context() -> None:
    """Clear request context (legacy no-token shim)."""
    _clear_request_context_with_token(None)


@contextmanager
def domain_context(
    *,
    partner_id: int | None = None,
    app_number: str | None = None,
    query_id: int | None = None,
) -> Iterator[None]:
    """Stamp business identifiers onto every nested log record.

    Usage::

        with domain_context(partner_id=partner.pk, app_number=app_number):
            response = make_http_request(...)  # logs carry partner_id + app_number

    Only kwargs supplied (not None) are pushed; tokens are reset in reverse
    order on exit so nested calls compose correctly.
    """
    tokens: list[tuple[contextvars.ContextVar[Any], contextvars.Token[Any]]] = []
    if partner_id is not None:
        tokens.append((_partner_id_var, _partner_id_var.set(partner_id)))
    if app_number is not None:
        tokens.append((_app_number_var, _app_number_var.set(app_number)))
    if query_id is not None:
        tokens.append((_query_id_var, _query_id_var.set(query_id)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


class RequestContextFilter(logging.Filter):
    """Logging filter that injects request_id + domain identifiers from contextvars.

    Example logging config::

        "filters": {
            "request_context": {
                "()": "core.utils.logging.RequestContextFilter",
            }
        }
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Inject context variables into the log record."""
        record.request_id = _request_id_var.get(None) or getattr(  # type: ignore[attr-defined]
            record, "request_id", None
        )
        # Domain identifiers — only set when something is in scope, so log
        # formatters that key on attribute existence still behave predictably.
        partner_id = _partner_id_var.get(None)
        if partner_id is not None and not hasattr(record, "partner_id"):
            record.partner_id = partner_id  # type: ignore[attr-defined]
        app_number = _app_number_var.get(None)
        if app_number is not None and not hasattr(record, "app_number"):
            record.app_number = app_number  # type: ignore[attr-defined]
        query_id = _query_id_var.get(None)
        if query_id is not None and not hasattr(record, "query_id"):
            record.query_id = query_id  # type: ignore[attr-defined]
        return True


@contextmanager
def log_duration(
    logger: logging.Logger, event: str, *, metric: bool = False, **extras: Any
) -> Iterator[None]:
    """Time a block and emit a single structured log line on exit.

    Emits one INFO record with ``duration_ms`` plus any caller-supplied extras.
    On exception, emits an ERROR record with ``ok=False`` and re-raises — the
    caller still sees the original traceback; no behavior change.

    When ``metric=True``, also tees the duration into ``core.metrics``. The
    shim only forwards labels that match the cardinality contract — extras
    like ``app_number`` / ``partner_id`` stay on the log record but are NOT
    sent to the metric. See ``docs/observability.md``.
    """
    start = time.perf_counter()
    status = "ok"
    try:
        yield
    except BaseException:
        status = "error"
        duration_ms = (time.perf_counter() - start) * 1000
        logger.error(
            "%s failed after %.2fms",
            event,
            duration_ms,
            extra={"event": event, "duration_ms": duration_ms, "ok": False, **extras},
            exc_info=True,
        )
        if metric:
            _record_metric_safe(event, duration_ms, status, extras)
        raise
    else:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s completed in %.2fms",
            event,
            duration_ms,
            extra={"event": event, "duration_ms": duration_ms, "ok": True, **extras},
        )
        if metric:
            _record_metric_safe(event, duration_ms, status, extras)


def _record_metric_safe(
    event: str,
    duration_ms: float,
    status: str,
    extras: dict[str, Any],
) -> None:
    """Tee duration into ``core.metrics`` with only bounded labels.

    Imported lazily so the shim's hard-fail cardinality contract doesn't
    fight with ``log_duration`` callers that legitimately pass unbounded
    labels for the log line (e.g. ``app_number``). Anything not in the
    bounded allow-list is silently dropped before forwarding.
    """
    from core.metrics import _BOUNDED_LABEL_KEYS, record_duration

    bounded = {
        k: v
        for k, v in extras.items()
        if k in _BOUNDED_LABEL_KEYS and isinstance(v, (str, int, float))
    }
    record_duration(event, duration_ms, status=status, **bounded)
