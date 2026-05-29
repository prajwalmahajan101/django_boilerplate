"""Backend health states for resilience subsystems.

Today every Valkey-backed subsystem (cache, circuit-breaker storage,
throttle counters) has a binary in-memory flag for "degraded or not."
That flag is enough for fail-open behaviour but loses an important
distinction worth encoding explicitly:

* DEGRADED — the backend was healthy and degraded mid-flight. Recovery
  is a flag flip; the backend object is still wired to a Valkey client.
* BOOT_FALLBACK — the backend was constructed with the Valkey client
  unreachable. The object is internally wired to in-memory storage and
  cannot recover via flag flip alone — the next call to ``get_backend``
  must rebuild the object against live Valkey.

The two states drive different recovery paths (see ``recovery.py``):
``DEGRADED`` recovers via in-call ``_try_recover()`` or background
``ValkeyRecoveryMonitor``; ``BOOT_FALLBACK`` recovers via
``reset_backend(alias)`` triggered from the readiness probe.
"""

from __future__ import annotations

import enum


class BackendHealth(enum.Enum):
    """Health state of a Valkey-backed resilience backend."""

    ACTIVE = "active"
    """Healthy — operations route through Valkey."""

    DEGRADED = "degraded"
    """Was ACTIVE, hit a failure, now serving from in-memory fallback.
    Recovery: in-call ``_try_recover`` (throttled to 30s) OR background
    ``ValkeyRecoveryMonitor`` flips this back to ACTIVE on a stable PING window."""

    BOOT_FALLBACK = "boot_fallback"
    """Constructed as in-memory because Valkey was unreachable at __init__.
    Recovery: ``reset_backend(alias)`` rebuilds the backend object against
    live Valkey; typically driven by the readiness probe."""

    @property
    def is_healthy(self) -> bool:
        return self is BackendHealth.ACTIVE

    @property
    def needs_object_rebuild(self) -> bool:
        return self is BackendHealth.BOOT_FALLBACK
