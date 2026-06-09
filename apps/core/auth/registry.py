"""Process-local registry of :class:`AuthProvider` implementations.

Providers self-register at :class:`AppConfig.ready` time. The chain
routes consult is the order of ``settings.AUTH_ENABLED_PROVIDERS``.
Unknown names are skipped with a one-shot WARNING so a typo never
silently disables authentication.
"""

from __future__ import annotations

import logging
import threading

from core.auth.base import AuthProvider
from django.conf import settings

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, AuthProvider] = {}
_WARNED_UNKNOWN: set[str] = set()
_lock = threading.Lock()


def register(provider: AuthProvider) -> None:
    """Register ``provider`` under its ``name``. Idempotent."""
    with _lock:
        _REGISTRY[provider.name] = provider


def unregister(name: str) -> None:
    """Drop ``name`` from the registry — primarily a test helper."""
    with _lock:
        _REGISTRY.pop(name, None)


def registered_names() -> list[str]:
    """Return the names of every currently-registered provider."""
    with _lock:
        return list(_REGISTRY)


def enabled_providers() -> list[AuthProvider]:
    """Return active providers in the order routes consult them."""
    names = list(getattr(settings, "AUTH_ENABLED_PROVIDERS", ["api_key"]))
    out: list[AuthProvider] = []
    for name in names:
        with _lock:
            provider = _REGISTRY.get(name)
            already_warned = name in _WARNED_UNKNOWN
            registered_snapshot = sorted(_REGISTRY) if provider is None else None
            if provider is None and not already_warned:
                _WARNED_UNKNOWN.add(name)
        if provider is None:
            if not already_warned:
                logger.warning(
                    "AUTH_ENABLED_PROVIDERS references unknown provider %r — "
                    "registered names: %s",
                    name,
                    registered_snapshot,
                )
            continue
        out.append(provider)
    return out


def _reset() -> None:
    """Drop all registered providers + warnings. Test helper."""
    with _lock:
        _REGISTRY.clear()
        _WARNED_UNKNOWN.clear()


__all__ = [
    "enabled_providers",
    "register",
    "registered_names",
    "unregister",
]
