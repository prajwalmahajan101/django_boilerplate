"""Throttle module with pluggable backends.

Default: Valkey-backed with atomic Lua scripts.
Fallback: DRF SimpleRateThrottle with cache provider.

The public class names (UserTierThrottle, BurstThrottle, etc.) are
resolved at import time via the provider and can be referenced
directly in Django settings::

    REST_FRAMEWORK = {
        "DEFAULT_THROTTLE_CLASSES": [
            "core.resilience.throttles.UserTierThrottle",
            "core.resilience.throttles.BurstThrottle",
            "core.resilience.throttles.GlobalThrottle",
        ],
    }
"""

from core.resilience.throttles.provider import get_throttle_classes, reset_throttle_classes

# Resolve classes at module level so DRF can find them via dotted paths.
# Uses lazy __getattr__ to defer resolution until first access, avoiding
# import-time side effects (Valkey connections during Django startup).

__all__ = [
    "UserTierThrottle",
    "BurstThrottle",
    "GlobalThrottle",
    "EndpointThrottle",
    "ValkeyRateThrottle",
    "get_throttle_classes",
    "reset_throttle_classes",
]


def __getattr__(name: str):
    if name in (
        "UserTierThrottle",
        "BurstThrottle",
        "GlobalThrottle",
        "EndpointThrottle",
        "ValkeyRateThrottle",
    ):
        classes = get_throttle_classes()
        if name in classes:
            return classes[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
