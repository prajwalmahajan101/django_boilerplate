"""Shared Valkey client utilities.

Centralizes the logic for obtaining a raw Valkey client from Django's cache
framework via the django-valkey backend.

Usage::

    from core.utils.valkey import get_valkey_client

    client = get_valkey_client("rate_limit")
    client.set("key", "value")

Dormant: ships in-tree for downstream forks but is not on the request path
today (zero in-tree callers as of M2). Omitted from the coverage gate. The
dormant-import AST gate scheduled for M3 will fail the build if anything
under ``apps/`` imports from this module without a matching integration test.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_valkey_client(cache_alias: str = "default") -> Any:
    """Get the raw Valkey client from a Django cache backend.

    Supports django-valkey's ``ValkeyCache`` backend which exposes the
    client via ``cache.client.get_client()``.

    Args:
        cache_alias: Django ``CACHES`` alias (e.g. ``"rate_limit"``).

    Returns:
        A ``valkey.Valkey`` (or compatible) client instance.

    Raises:
        AttributeError: If the cache backend does not expose a Valkey client.
    """
    from django.core.cache import caches

    cache = caches[cache_alias]

    # django-valkey backend
    if hasattr(cache, "client"):
        return cache.client.get_client()

    # Django's native RedisCache backend (Django 4.0+) — fallback.
    # Note: _cache is a private attribute; tested on Django 5.x–6.0.
    try:
        if hasattr(cache, "_cache"):
            return cache._cache.get_client()
    except AttributeError:
        pass  # Fall through to the error below

    raise AttributeError(
        f"Cannot get Valkey client from cache backend '{cache_alias}' "
        f"(type: {type(cache).__name__}). Expected django-valkey ValkeyCache."
    )
