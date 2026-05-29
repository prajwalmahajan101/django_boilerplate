"""``@log_function`` decorator — async+sync entry/exit/error tracing.

Off by default; flipped on via the ``FUNCTION_LOGGING_ENABLED`` env
var (typically ``true`` in dev). ERROR-level failure logs fire
unconditionally so a prod outage still leaves a trace; entry/exit are
DEBUG-only and zero-cost when the flag is off.

Distinct from :func:`apps.core.utils.logging.log_duration`, which
times a single explicit block and emits one INFO record on exit.
``log_function`` is the per-call decorator variant — useful for
sprinkling temporary visibility into a service method when chasing a
bug, without rewriting the call site.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import time
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar, cast

P = ParamSpec("P")
R = TypeVar("R")


def is_function_logging_enabled() -> bool:
    """Return True when the decorator should emit DEBUG entry/exit records.

    Reads ``FUNCTION_LOGGING_ENABLED`` at call time so a test can flip
    the flag with ``monkeypatch.setenv`` without re-importing the
    module.
    """
    return os.getenv("FUNCTION_LOGGING_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _summarize(obj: Any, max_length: int = 200) -> str:
    """Compact, log-safe string view of *obj*.

    Avoids ``repr``ing large collections (a 10k-element list would blow
    the log line) by reporting shape + length for dict/list/tuple.
    Scalars are stringified and truncated.
    """
    try:
        if isinstance(obj, dict):
            return f"<dict with {len(obj)} keys>"
        if isinstance(obj, list):
            return f"<list with {len(obj)} items>"
        if isinstance(obj, tuple):
            return f"<tuple with {len(obj)} items>" if obj else "<tuple>"
        if isinstance(obj, (str, int, float, bool)) or obj is None:
            text = str(obj)
            return text[:max_length] + "..." if len(text) > max_length else text
        return f"<{type(obj).__name__}>"
    except Exception:
        return "<unserializable>"


def _log_enter(
    log: logging.Logger,
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    if not is_function_logging_enabled():
        return
    log.debug(
        "Executing %s",
        func.__name__,
        extra={
            "func_args": _summarize(args),
            "func_kwargs": _summarize(kwargs),
            "args_count": len(args),
            "kwargs_count": len(kwargs),
            "event": "function_enter",
        },
    )


def _log_exit(
    log: logging.Logger,
    func: Callable[..., Any],
    result: Any,
    start: float,
    end: float,
) -> None:
    if not is_function_logging_enabled():
        return
    duration = end - start
    log.debug(
        "Completed %s",
        func.__name__,
        extra={
            "duration_seconds": round(duration, 3),
            "duration_ms": round(duration * 1000, 2),
            "result_summary": _summarize(result),
            "result_type": type(result).__name__,
            "event": "function_exit",
        },
    )


def _log_error(
    log: logging.Logger,
    func: Callable[..., Any],
    start: float,
    end: float,
    exc: BaseException,
) -> None:
    """ERROR + DEBUG records for a raised exception.

    The ERROR record is always emitted (so prod sees the failure even
    when function tracing is off); the DEBUG record adds the full
    stack via ``exc_info=True``.
    """
    duration = end - start
    log.error(
        "Function %s failed: %s",
        func.__name__,
        type(exc).__name__,
        extra={
            "error_type": type(exc).__name__,
            "error_message": _summarize(str(exc), max_length=200),
            "duration_seconds": round(duration, 3),
            "event": "function_error",
        },
    )
    log.debug(
        "Function %s raised exception - full stack trace",
        func.__name__,
        extra={
            "duration_seconds": duration,
            "duration_ms": round(duration * 1000, 2),
            "error_type": type(exc).__name__,
            "error_message_full": str(exc),
            "error_class": exc.__class__.__name__,
            "error_module": type(exc).__module__,
            "event": "function_error_detailed",
        },
        exc_info=True,
    )


def log_function(
    logger: logging.Logger | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorate a callable to log entry, exit, and errors (sync or async).

    Args:
        logger: Logger to emit on. Defaults to the wrapped function's
            module logger, so each module's logs land under its own name.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        log = logger or logging.getLogger(func.__module__)

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                start = time.perf_counter()
                _log_enter(log, func, args, kwargs)
                try:
                    result = await func(*args, **kwargs)
                    _log_exit(log, func, result, start, time.perf_counter())
                    return result
                except Exception as exc:
                    _log_error(log, func, start, time.perf_counter(), exc)
                    raise

            return cast(Callable[P, R], async_wrapper)

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            start = time.perf_counter()
            _log_enter(log, func, args, kwargs)
            try:
                result = func(*args, **kwargs)
                _log_exit(log, func, result, start, time.perf_counter())
                return result
            except Exception as exc:
                _log_error(log, func, start, time.perf_counter(), exc)
                raise

        return cast(Callable[P, R], sync_wrapper)

    return decorator


__all__ = ["is_function_logging_enabled", "log_function"]
