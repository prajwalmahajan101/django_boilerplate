"""Factory/provider for throttle classes.

Detects Valkey availability and returns the appropriate set of throttle classes.
Default: Valkey-backed with Lua atomicity.
Fallback: DRF SimpleRateThrottle with cache provider.

Usage::

    from core.resilience.throttles.provider import get_throttle_classes

    classes = get_throttle_classes()
    UserTierThrottle = classes["UserTierThrottle"]
"""

from __future__ import annotations

import logging
from threading import Lock

logger = logging.getLogger(__name__)

_throttle_classes: dict[str, type] | None = None
_lock = Lock()


def get_throttle_classes() -> dict[str, type]:
    """Get the resolved throttle classes (Valkey or DRF fallback).

    Returns a dict mapping class names to the appropriate implementation.
    Result is cached as a singleton.
    """
    global _throttle_classes

    if _throttle_classes is not None:
        return _throttle_classes

    with _lock:
        if _throttle_classes is not None:
            return _throttle_classes

        _throttle_classes = _resolve_classes()
        return _throttle_classes


def _resolve_classes() -> dict[str, type]:
    """Determine which throttle implementation to use."""
    try:
        from core.utils.valkey import get_valkey_client

        client = get_valkey_client("rate_limit")
        client.ping()

        from core.resilience.throttles.valkey_impl import (
            BurstThrottle,
            EndpointThrottle,
            GlobalThrottle,
            UserTierThrottle,
            ValkeyRateThrottle,
        )

        logger.info("Using Valkey-backed throttle classes")
        return {
            "UserTierThrottle": UserTierThrottle,
            "BurstThrottle": BurstThrottle,
            "GlobalThrottle": GlobalThrottle,
            "EndpointThrottle": EndpointThrottle,
            "ValkeyRateThrottle": ValkeyRateThrottle,
        }

    except Exception as e:
        logger.warning(
            "Valkey unavailable for throttling, using DRF fallback: %s", e
        )

        from core.resilience.throttles.drf_impl import (
            DRFBurstThrottle,
            DRFEndpointThrottle,
            DRFGlobalThrottle,
            DRFUserTierThrottle,
            DRFBaseThrottle,
        )

        return {
            "UserTierThrottle": DRFUserTierThrottle,
            "BurstThrottle": DRFBurstThrottle,
            "GlobalThrottle": DRFGlobalThrottle,
            "EndpointThrottle": DRFEndpointThrottle,
            "ValkeyRateThrottle": DRFBaseThrottle,
        }


def reset_throttle_classes() -> None:
    """Reset the singleton (for testing only)."""
    global _throttle_classes
    with _lock:
        _throttle_classes = None


def reset_throttle_backend(_alias: str = "default") -> bool:
    """Re-resolve throttle classes against current Valkey state.

    When Valkey returns after being unreachable at boot, the DRF-fallback
    throttle classes will keep serving until the singleton is rebuilt.
    Called by ``core.resilience.recovery.reset_backend("throttle:...")``.

    Returns True if the throttle resolution was discarded — the next
    call to ``get_throttle_classes`` will probe Valkey fresh. Throttle
    counters themselves are stateless across the swap; the on-disk /
    in-memory state isn't preserved (documented in docs/resilience.md
    as "drop in-memory counters on re-attach — accept a brief gap").
    """
    global _throttle_classes
    with _lock:
        if _throttle_classes is None:
            return False
        _throttle_classes = None
        logger.info("reset_throttle_backend: throttle class resolution discarded")
    return True
