"""Centralised reset of process-level singletons between tests.

Tests that share a process inherit any module-level mutable state the
codebase keeps for performance (circuit-breaker registry, throttle
scope counters, fire-and-forget queues, the Fernet cipher cache,
Django's in-memory caches). Resetting them one-by-one at each call
site is brittle; this helper resets them all in dependency order so
the autouse ``_clear_caches`` fixture can stay a single one-liner.

Mirrors the FastAPI sibling's ``src.core.testing.reset`` so cross-repo
test plumbing keeps the same vocabulary.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def reset_all_singletons() -> None:
    """Drop every module-level singleton the test suite touches."""
    _reset_django_caches()
    _reset_resilience_registry()
    _reset_fire_and_forget_queues()
    _reset_fernet_cache()
    _reset_task_registry()


def _reset_django_caches() -> None:
    try:
        from django.core.cache import caches

        for cache in caches.all():
            try:
                cache.clear()
            except Exception:
                pass
    except Exception:
        logger.debug("django caches reset skipped", exc_info=True)


def _reset_resilience_registry() -> None:
    try:
        from core.resilience.registry import registry

        with registry._lock:
            registry._breakers.clear()
    except Exception:
        logger.debug("resilience registry reset skipped", exc_info=True)


def _reset_fire_and_forget_queues() -> None:
    try:
        from core.dispatch.fire_and_forget import drain_all

        drain_all(timeout=0.5)
    except Exception:
        logger.debug("fire_and_forget drain skipped", exc_info=True)


def _reset_fernet_cache() -> None:
    try:
        from core.utils import crypto

        crypto.reset_cache()
    except Exception:
        logger.debug("crypto cache reset skipped", exc_info=True)


def _reset_task_registry() -> None:
    try:
        from core.tasks.registry import _reset_registry

        _reset_registry()
    except Exception:
        logger.debug("task registry reset skipped", exc_info=True)


__all__ = ["reset_all_singletons"]
