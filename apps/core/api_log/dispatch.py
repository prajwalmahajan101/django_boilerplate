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
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from core.api_log import factory

logger = logging.getLogger(__name__)


def fire_and_forget(row: dict) -> None:
    """Hand a built audit row off to the api_log queue + backend."""
    try:
        queue = factory.get_apilog_queue()
        backend = factory.get_backend()
        queue.submit(lambda r=row: backend.persist(r))
    except Exception:
        logger.exception("api_log dispatch failed; row dropped")


def capture_and_dispatch(
    fn: Callable[..., Any],
    args: tuple,
    kwargs: dict,
    build_row: Callable[[Any, BaseException | None, float], dict],
) -> Any:
    """Run ``fn``, time it, build + queue the audit row, return / re-raise.

    Args:
        fn: The wrapped callable (sync).
        args, kwargs: Positional + keyword arguments forwarded to ``fn``.
        build_row: ``(result, exc, elapsed_ms) -> row_dict`` — invoked
            after the call. Exactly one of ``result`` / ``exc`` is
            non-None.
    """
    from core.utils.timing import perf_timer

    with perf_timer() as t:
        try:
            result = fn(*args, **kwargs)
        except BaseException as exc:
            elapsed = t.elapsed_ms
            try:
                row = build_row(None, exc, elapsed)
                fire_and_forget(row)
            except Exception:
                logger.exception("api_log build_row failed (error path)")
            raise

    try:
        row = build_row(result, None, t.elapsed_ms)
        fire_and_forget(row)
    except Exception:
        logger.exception("api_log build_row failed (success path)")
    return result


__all__ = ["capture_and_dispatch", "fire_and_forget"]
