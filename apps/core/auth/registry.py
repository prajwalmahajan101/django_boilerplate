"""Process-local registry of :class:`AuthProvider` implementations.

Providers self-register at :class:`AppConfig.ready` time. The chain
routes consult is the order of ``settings.AUTH_ENABLED_PROVIDERS``.
Unknown names are skipped with a one-shot WARNING so a typo never
silently disables authentication.
"""

from __future__ import annotations

import logging

from django.conf import settings

from core.auth.base import AuthProvider

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, AuthProvider] = {}
_WARNED_UNKNOWN: set[str] = set()


def register(provider: AuthProvider) -> None:
    """Register ``provider`` under its ``name``. Idempotent."""
    _REGISTRY[provider.name] = provider


def unregister(name: str) -> None:
    """Drop ``name`` from the registry — primarily a test helper."""
    _REGISTRY.pop(name, None)


def registered_names() -> list[str]:
    """Return the names of every currently-registered provider."""
    return list(_REGISTRY)


def enabled_providers() -> list[AuthProvider]:
    """Return active providers in the order routes consult them."""
    names = list(getattr(settings, "AUTH_ENABLED_PROVIDERS", ["api_key"]))
    out: list[AuthProvider] = []
    for name in names:
        provider = _REGISTRY.get(name)
        if provider is None:
            if name not in _WARNED_UNKNOWN:
                logger.warning(
                    "AUTH_ENABLED_PROVIDERS references unknown provider %r — "
                    "registered names: %s",
                    name,
                    sorted(_REGISTRY),
                )
                _WARNED_UNKNOWN.add(name)
            continue
        out.append(provider)
    return out


def _reset() -> None:
    """Drop all registered providers + warnings. Test helper."""
    _REGISTRY.clear()
    _WARNED_UNKNOWN.clear()


__all__ = [
    "enabled_providers",
    "register",
    "registered_names",
    "unregister",
]
