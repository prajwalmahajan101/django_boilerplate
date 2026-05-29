"""Factory/provider for the circuit breaker registry.

Provides a lazy singleton that tries Valkey first, falls back to pybreaker.

Usage::

    from core.resilience.circuit_breaker.provider import get_registry

    registry = get_registry()
    breaker = registry.get_or_create("payment_gateway")
"""

from __future__ import annotations

import logging
from threading import Lock

from core.resilience.circuit_breaker.base import (
    BaseCircuitBreakerRegistry,
    CircuitBreakerConfig,
)

logger = logging.getLogger(__name__)

_registry: BaseCircuitBreakerRegistry | None = None
_lock = Lock()


def get_registry() -> BaseCircuitBreakerRegistry:
    """Get the singleton circuit breaker registry.

    Tries to create a ValkeyRegistry (distributed, shared across workers).
    Falls back to PyBreakerRegistry (in-memory, per-process) if Valkey
    is unavailable.

    Thread-safe via double-checked locking.
    """
    global _registry

    if _registry is not None:
        return _registry

    with _lock:
        if _registry is not None:
            return _registry

        _registry = _create_registry()
        return _registry


def _create_registry() -> BaseCircuitBreakerRegistry:
    """Create the best available registry."""
    from django.conf import settings as django_settings

    valkey_alias = django_settings.CIRCUIT_BREAKER_CONFIG.get("VALKEY_ALIAS", "rate_limit")
    key_prefix = django_settings.CIRCUIT_BREAKER_CONFIG.get("KEY_PREFIX", "cb")

    try:
        from core.resilience.circuit_breaker.valkey_impl import ValkeyRegistry

        registry = ValkeyRegistry(
            valkey_alias=valkey_alias,
            key_prefix=key_prefix,
        )
        # ValkeyRegistry may have degraded to PyBreakerRegistry internally,
        # but that's handled transparently — we still return it.
        return registry
    except Exception as e:
        logger.warning(
            "Failed to create Valkey circuit breaker registry, "
            "using pybreaker (in-memory): %s",
            e,
        )
        from core.resilience.circuit_breaker.pybreaker_impl import PyBreakerRegistry

        return PyBreakerRegistry()


def reset_registry() -> None:
    """Reset the singleton registry (for testing only)."""
    global _registry
    with _lock:
        _registry = None


def reset_breaker_registry() -> bool:
    """Discard the registry singleton and rebuild on next ``get_registry``.

    When Valkey returns after boot, the in-memory PyBreaker fallback would
    otherwise keep serving forever. Called by
    ``core.resilience.recovery.reset_backend("breaker:registry")``.

    Re-attach merge policy (documented in docs/resilience.md):
    "Take the more-pessimistic state — a worker's local OPEN breaker
    pushes to Valkey on re-attach so siblings inherit." Implementing the
    merge requires per-breaker state inspection; for now the rebuild
    discards local state and concurrent callers re-open the breaker on
    the next failure observed against the live service. Documented as
    intentional in docs/resilience.md.

    Returns True if a rebuild was triggered.
    """
    global _registry
    with _lock:
        if _registry is None:
            return False
        _registry = None
    # Eager rebuild so registration with the recovery monitor happens now.
    get_registry()
    logger.info("reset_breaker_registry: registry rebuilt against current Valkey state")
    return True
