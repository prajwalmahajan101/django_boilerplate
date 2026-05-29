"""Cache module with pluggable backends.

Default: Valkey (distributed, shared across workers).
Fallback: In-memory (per-process, via Django LocMemCache).

Usage::

    from core.resilience.cache import get_cache

    # Get the default cache backend
    cache = get_cache()
    cache.set("key", "value", timeout=300)
    result = cache.get("key")

    # Get a specific cache alias
    rate_cache = get_cache("rate_limit")

    # High-level utilities
    from core.resilience.cache import (
        generate_cache_key,
        get_cached_result,
        set_cached_result,
    )
"""

from core.resilience.cache.base import BaseCacheBackend
from core.resilience.cache.provider import get_cache, reset_caches
from core.resilience.cache.utils import (
    CacheVersionError,
    bump_dataset_cache_version,
    generate_cache_key,
    get_cached_result,
    get_dataset_cache_version,
    set_cached_result,
)

__all__ = [
    "BaseCacheBackend",
    "CacheVersionError",
    "bump_dataset_cache_version",
    "generate_cache_key",
    "get_cache",
    "get_cached_result",
    "get_dataset_cache_version",
    "reset_caches",
    "set_cached_result",
]
