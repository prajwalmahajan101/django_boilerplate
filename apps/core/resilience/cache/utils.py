"""High-level caching utilities built on top of the cache provider.

Provides key generation, fail-open get/set, and per-dataset cache versioning.
"""

import hashlib
import json
import logging
from typing import Any

from core.exceptions.infrastructure import InfrastructureError
from core.resilience.cache.provider import get_cache

logger = logging.getLogger(__name__)

_CACHE_KEY_VERSION = 1


class CacheVersionError(InfrastructureError):
    """Raised when the cache backend cannot reliably bump a version counter.

    Surfaces as HTTP 500 via the ``InfrastructureError`` default mapping —
    this is an internal failure (cache backend misbehaving), not caller error.
    """

    default_message = "Cache version bump failed."
    error_code = "CACHE_VERSION_ERROR"


def _serialize_params(params: dict | None) -> str:
    """Serialize params deterministically using JSON."""
    if not params:
        return "{}"
    return json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)


def generate_cache_key(
    prefix: str,
    query: str,
    params: dict | None,
    user_id: int | str | None = None,
    datasource_id: int | None = None,
) -> str:
    """Generate deterministic cache key from query, params, and context."""
    cache_components = [
        f"query={query}",
        f"params={_serialize_params(params)}",
    ]
    if user_id is not None:
        cache_components.append(f"user={user_id}")
    if datasource_id is not None:
        cache_components.append(f"ds={datasource_id}")

    cache_data = "|".join(cache_components)
    hash_digest = hashlib.sha256(cache_data.encode("utf-8")).hexdigest()
    return f"{prefix}:v{_CACHE_KEY_VERSION}:{hash_digest}"


def get_cached_result(cache_key: str) -> Any | None:
    """Get cached result. Fails open (returns None) on errors."""
    try:
        cache = get_cache()
        result = cache.get(cache_key)
    except Exception:
        logger.warning(
            "Cache GET failed (failing open as cache miss), key: %s",
            cache_key[:50],
            exc_info=True,
        )
        return None
    if result is not None:
        logger.debug("Cache hit for key: %s", cache_key[:50])
    else:
        logger.debug("Cache miss for key: %s", cache_key[:50])
    return result


def set_cached_result(cache_key: str, value: Any, timeout: int) -> None:
    """Set cached result. Fails open (silently logs) on errors."""
    try:
        cache = get_cache()
        cache.set(cache_key, value, timeout=timeout)
        logger.debug("Cached result for %d seconds, key: %s", timeout, cache_key[:50])
    except Exception:
        logger.warning(
            "Cache SET failed (failing open, result not cached), key: %s",
            cache_key[:50],
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Per-dataset cache versioning
# ---------------------------------------------------------------------------
_DATASET_VERSION_KEY_PREFIX = "dataset_cache_version"


def _dataset_version_key(dataset_id: int) -> str:
    return f"{_DATASET_VERSION_KEY_PREFIX}:{dataset_id}"


def get_dataset_cache_version(dataset_id: int) -> int:
    """Return the current cache version for a dataset (defaults to 0)."""
    try:
        cache = get_cache()
        version = cache.get(_dataset_version_key(dataset_id))
    except Exception:
        logger.warning(
            "Cache GET failed for dataset version (failing open, using version 0), "
            "dataset_id: %d",
            dataset_id,
            exc_info=True,
        )
        return 0
    return int(version) if version is not None else 0


def bump_dataset_cache_version(dataset_id: int) -> int:
    """Increment the cache version for *dataset_id* atomically."""
    cache = get_cache()
    key = _dataset_version_key(dataset_id)

    try:
        new_version = cache.incr(key)
        logger.info(
            "Bumped dataset cache version to %d for dataset %d",
            new_version,
            dataset_id,
        )
        return new_version
    except ValueError:
        pass

    if cache.add(key, 1, timeout=None):
        logger.info(
            "Initialized dataset cache version to 1 for dataset %d",
            dataset_id,
        )
        return 1

    try:
        new_version = cache.incr(key)
        logger.info(
            "Bumped dataset cache version to %d for dataset %d (retry)",
            new_version,
            dataset_id,
        )
        return new_version
    except ValueError as err:
        raise CacheVersionError(
            f"Failed to bump cache version for dataset {dataset_id}: "
            "key disappeared between add() and incr(). "
            "Check cache backend health."
        ) from err
