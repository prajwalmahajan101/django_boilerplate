"""In-memory cache backend using Django's LocMemCache.

Used as fallback when Valkey is unavailable. Per-process, not shared
across workers, and cleared on restart.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.cache.backends.locmem import LocMemCache

from core.resilience.cache.base import BaseCacheBackend

logger = logging.getLogger(__name__)


class InMemoryCacheBackend(BaseCacheBackend):
    """In-memory cache backed by Django's LocMemCache.

    Suitable as a fallback — provides correct semantics (get/set/incr/add)
    but is per-process and not shared across workers.
    """

    def __init__(self, location: str = "core-fallback", params: dict | None = None) -> None:
        self._cache = LocMemCache(location, params or {})

    @property
    def backend_name(self) -> str:
        return "inmemory"

    def get(self, key: str) -> Any | None:
        return self._cache.get(key)

    def set(self, key: str, value: Any, timeout: int | None = None) -> None:
        self._cache.set(key, value, timeout=timeout)

    def delete(self, key: str) -> None:
        self._cache.delete(key)

    def incr(self, key: str) -> int:
        return self._cache.incr(key)

    def add(self, key: str, value: Any, timeout: int | None = None) -> bool:
        return self._cache.add(key, value, timeout=timeout)

    def clear(self) -> None:
        self._cache.clear()

    def is_healthy(self) -> bool:
        return True  # In-memory is always available
