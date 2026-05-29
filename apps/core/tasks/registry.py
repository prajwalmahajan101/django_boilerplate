"""Task decorator + process-local registry.

:func:`register_task` is a thin wrapper around :func:`celery.shared_task`
that also records the resulting task name in a local registry. The
registry exists mainly so tests can introspect what was wired up
without reaching into Celery's private internals; the worker still
discovers tasks through Celery's own autodiscover mechanism.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from celery import shared_task

_registry: dict[str, Any] = {}
_lock = threading.Lock()


def register_task(
    fn: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    **task_kwargs: Any,
) -> Callable[..., Any]:
    """Wrap ``fn`` as a Celery task and record it in the local registry.

    Usage::

        @register_task
        def send_welcome_email(user_id: int) -> None:
            ...

        @register_task(name="emails.send_welcome", queue="emails")
        def send_welcome_email(user_id: int) -> None:
            ...
    """

    def _decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        task_name = name or f"{func.__module__}.{func.__qualname__}"
        task = shared_task(name=task_name, **task_kwargs)(func)
        with _lock:
            _registry[task_name] = task
        return task

    if fn is not None:
        return _decorate(fn)
    return _decorate


def registered_tasks() -> dict[str, Any]:
    """Return a copy of the registry — test-only introspection."""
    with _lock:
        return dict(_registry)


def _reset_registry() -> None:
    """Drop all registered tasks. Test helper."""
    with _lock:
        _registry.clear()


__all__ = ["register_task", "registered_tasks"]
