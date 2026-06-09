"""Time-and-dispatch orchestrator shared by inbound + outbound decorators.

``capture_and_dispatch`` runs the wrapped callable inside a
:func:`apps.core.utils.timing.perf_timer`, builds the audit row via a
caller-supplied ``build_row`` closure (which inspects the result or
exception), and queues persistence through the api_log
fire-and-forget queue. The wrapped callable's result / exception are
returned / re-raised unmodified — the request path observes no
behaviour change.

This module never raises into the wrapped call site. A failure to
build, queue, or persist the audit row is logged and swallowed.

Every failure-side ``logger.exception`` call carries an ``extra=``
payload of ``service_name`` / ``direction`` / ``request_id`` /
``log_id`` so a "lost audit row" investigation can trace from the log
back to the originating service without guesswork. The same
``log_id`` is also threaded into ``build_row`` so the same id appears
on the persisted audit row (when build_row succeeds) and on every
failure log for the call. Mirrors fastapi_boilerplate ISSUE-021.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any

from core.api_log import factory
from core.utils.logging import _request_id_var

logger = logging.getLogger(__name__)


def _correlation_extra(
    *,
    service_name: str | None,
    direction: str | None,
    log_id: str | None,
) -> dict[str, str | None]:
    """Assemble the standard correlation payload for failure logs."""
    return {
        "service_name": service_name,
        "direction": direction,
        "request_id": _request_id_var.get(None),
        "log_id": log_id,
    }


def fire_and_forget(
    row: dict,
    *,
    service_name: str | None = None,
    direction: str | None = None,
    log_id: str | None = None,
) -> None:
    """Hand a built audit row off to the api_log queue + backend."""
    try:
        queue = factory.get_apilog_queue()
        backend = factory.get_backend()
        queue.submit(lambda r=row: backend.persist(r))
    except Exception:
        logger.exception(
            "api_log dispatch failed; row dropped",
            extra=_correlation_extra(service_name=service_name, direction=direction, log_id=log_id),
        )


def capture_and_dispatch(
    fn: Callable[..., Any],
    args: tuple,
    kwargs: dict,
    build_row: Callable[..., dict],
    *,
    service_name: str | None = None,
    direction: str | None = None,
) -> Any:
    """Run ``fn``, time it, build + queue the audit row, return / re-raise.

    Args:
        fn: The wrapped callable (sync).
        args, kwargs: Positional + keyword arguments forwarded to ``fn``.
        build_row: ``(result, exc, elapsed_ms, *, log_id=...) -> row_dict``
            — invoked after the call. Exactly one of ``result`` /
            ``exc`` is non-None. The ``log_id`` kwarg is optional;
            callers that ignore it stay back-compat.
        service_name: Logical service tag for correlation logs. Pure
            metadata; not threaded into the row.
        direction: ``"inbound"`` / ``"outbound"`` — correlation only.
    """
    from core.utils.timing import perf_timer

    log_id = str(uuid.uuid4())

    def _build(result: Any, exc: BaseException | None, elapsed_ms: float) -> dict:
        # Forward log_id when the builder accepts it; fall back for
        # signatures that don't take the kwarg.
        try:
            return build_row(result, exc, elapsed_ms, log_id=log_id)
        except TypeError:
            return build_row(result, exc, elapsed_ms)

    with perf_timer() as t:
        try:
            result = fn(*args, **kwargs)
        except BaseException as exc:
            elapsed = t.elapsed_ms
            try:
                row = _build(None, exc, elapsed)
                fire_and_forget(
                    row,
                    service_name=service_name,
                    direction=direction,
                    log_id=log_id,
                )
            except Exception:
                logger.exception(
                    "api_log build_row failed (error path)",
                    extra=_correlation_extra(
                        service_name=service_name,
                        direction=direction,
                        log_id=log_id,
                    ),
                )
            raise

    try:
        row = _build(result, None, t.elapsed_ms)
        fire_and_forget(
            row,
            service_name=service_name,
            direction=direction,
            log_id=log_id,
        )
    except Exception:
        logger.exception(
            "api_log build_row failed (success path)",
            extra=_correlation_extra(service_name=service_name, direction=direction, log_id=log_id),
        )
    return result


__all__ = ["capture_and_dispatch", "fire_and_forget"]
