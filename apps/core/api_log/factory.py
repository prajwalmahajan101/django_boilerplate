"""Backend selection + queue wiring for the api_log pipeline.

Backend is chosen by ``API_LOG_BACKEND`` (default ``orm``); the
fire-and-forget queue is named ``api_log`` and is bounded by
``API_LOG_QUEUE_MAX_IN_FLIGHT`` (default 1000) with
``API_LOG_QUEUE_WORKERS`` (default 4) consumer threads. See ADR-0001
for the dispatch model.
"""

from __future__ import annotations

import logging
import threading

from core.api_log.backends import NoopApiLogBackend, OrmApiLogBackend
from core.api_log.backends.base import ApiLogBackend
from core.dispatch.fire_and_forget import FireAndForgetQueue, get_queue
from django.conf import settings

logger = logging.getLogger(__name__)

_QUEUE_NAME = "api_log"
_backend_lock = threading.Lock()
_backend: ApiLogBackend | None = None


def _build_backend() -> ApiLogBackend:
    name = str(getattr(settings, "API_LOG_BACKEND", "orm")).strip().lower()
    if name == "noop":
        return NoopApiLogBackend()
    if name in ("orm", "django", "db"):
        return OrmApiLogBackend()
    logger.warning("Unknown API_LOG_BACKEND=%r; defaulting to orm.", name)
    return OrmApiLogBackend()


def init_repository() -> None:
    """Resolve and cache the configured backend + the queue."""
    global _backend
    with _backend_lock:
        if _backend is None:
            _backend = _build_backend()
    # Ensure the named queue exists at AppConfig.ready() time so the
    # first request does not pay the executor-spinup cost.
    _ensure_queue()


def _ensure_queue() -> FireAndForgetQueue:
    try:
        return get_queue(_QUEUE_NAME)
    except KeyError:
        return FireAndForgetQueue(
            _QUEUE_NAME,
            max_in_flight=int(getattr(settings, "API_LOG_QUEUE_MAX_IN_FLIGHT", 1000)),
            max_workers=int(getattr(settings, "API_LOG_QUEUE_WORKERS", 4)),
        )


def get_backend() -> ApiLogBackend:
    """Return the cached backend, building it on first call if needed."""
    global _backend
    if _backend is None:
        with _backend_lock:
            if _backend is None:
                _backend = _build_backend()
    return _backend


def get_apilog_queue() -> FireAndForgetQueue:
    """Return the lazily-built fire-and-forget queue used by the api_log pipeline."""
    return _ensure_queue()


def reset_for_tests() -> None:
    """Drop the cached backend so the next access re-reads settings."""
    global _backend
    with _backend_lock:
        _backend = None


__all__ = [
    "get_apilog_queue",
    "get_backend",
    "init_repository",
    "reset_for_tests",
]
