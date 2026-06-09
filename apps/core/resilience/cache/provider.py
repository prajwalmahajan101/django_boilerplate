"""Factory/provider for the cache backend.

Provides lazy singletons that try Valkey first, fall back to in-memory.

Usage::

    from core.resilience.cache.provider import get_cache

    cache = get_cache()            # default alias
    cache = get_cache("rate_limit") # specific alias

    cache.set("key", "value", timeout=300)
    result = cache.get("key")
"""

from __future__ import annotations

import logging
from threading import Lock

from core.resilience.cache.base import BaseCacheBackend

logger = logging.getLogger(__name__)

_caches: dict[str, BaseCacheBackend] = {}
_lock = Lock()


def get_cache(alias: str = "default") -> BaseCacheBackend:
    """Get a cache backend singleton for the given alias.

    Tries ValkeyCacheBackend first (distributed, shared across workers).
    Falls back to InMemoryCacheBackend (per-process) if Valkey is unavailable.

    Thread-safe via double-checked locking.
    """
    cache = _caches.get(alias)
    if cache is not None:
        return cache

    with _lock:
        if alias not in _caches:
            _caches[alias] = _create_cache(alias)
        return _caches[alias]


def _create_cache(alias: str) -> BaseCacheBackend:
    """Create the best available cache backend."""
    try:
        from core.resilience.cache.valkey_impl import ValkeyCacheBackend

        return ValkeyCacheBackend(cache_alias=alias)
    except Exception as e:
        logger.warning(
            "Failed to create Valkey cache backend (alias=%s), " "using in-memory: %s",
            alias,
            e,
        )
        from core.resilience.cache.inmemory_impl import InMemoryCacheBackend

        return InMemoryCacheBackend(location=f"fallback-{alias}")


def reset_caches() -> None:
    """Reset all cache singletons (for testing only)."""
    with _lock:
        _caches.clear()


def reset_cache_backend(alias: str) -> bool:
    """Discard the singleton for ``alias`` and rebuild on next ``get_cache``.

    The new instance attempts the Valkey connection fresh. Used by the
    readiness probe to recover a ``BOOT_FALLBACK`` cache backend — the
    in-memory instance cannot recover by flag flip because it never had
    a Valkey client to reconnect.

    Returns True if a rebuild happened.
    """
    with _lock:
        if alias not in _caches:
            return False
        old = _caches.pop(alias)
        logger.info(
            "reset_cache_backend(%s): replacing %s",
            alias,
            type(old).__name__,
        )
    # Rebuild eagerly so registration with the recovery monitor happens now,
    # not on the next caller's lookup.
    get_cache(alias)
    return True
