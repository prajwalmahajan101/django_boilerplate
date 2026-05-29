"""Dual-recovery model for Valkey-backed resilience subsystems.

Three subsystems fail-open to in-memory when Valkey is unreachable:
``cache``, ``circuit_breaker`` storage, ``throttle`` counters. Without
recovery, a 30-second Valkey blip leaves every worker process serving
from local memory until the next restart — a silent split-brain.

This module adds three recovery paths that operate simultaneously:

1. **Background probe** — ``ValkeyRecoveryMonitor`` runs one daemon
   thread per process. While any registered backend is non-ACTIVE it
   PINGs Valkey every ``VALKEY_RECOVERY_PROBE_SECONDS`` (default 10s).
   On a stable success window (3 consecutive successes) it iterates
   registered backends and dispatches recovery.
2. **In-call probe** — each subsystem's degraded code path calls
   ``_try_recover()`` no more often than ``_RECOVERY_PROBE_INTERVAL_S``
   (30s). This is defence-in-depth so recovery doesn't depend on the
   monitor thread being alive.
3. **Readiness-driven rebuild** — the ``/api/readiness/`` endpoint calls
   ``reset_backend(alias)`` on any backend currently in
   ``BOOT_FALLBACK``. This is the only path that recovers a backend
   whose Valkey client was unreachable at ``__init__``.

Direct port of patterns from
``colending_partner/src/core/resilience/{cache,lifecycle}``. Vocabulary
intentionally mirrors the sibling so an operator who knows one project's
resilience model knows the other.
"""

from __future__ import annotations

import logging
import threading
import time
import weakref
from typing import Any, Callable, Protocol, runtime_checkable

from core.resilience.health import BackendHealth

logger = logging.getLogger(__name__)


_RECOVERY_PROBE_INTERVAL_S = 30.0
_STABLE_WINDOW_SUCCESSES = 3


@runtime_checkable
class RecoverableBackend(Protocol):
    """Contract every Valkey-backed backend opts into to receive recovery.

    Implementations need not subclass — duck typing via ``Protocol`` keeps
    cache / breaker-storage / throttle implementations decoupled from this
    module.
    """

    alias: str
    """Stable identifier (e.g. ``cache:default``, ``throttle:counters``)."""

    @property
    def health(self) -> BackendHealth:  # pragma: no cover - structural
        ...

    def try_recover(self) -> bool:  # pragma: no cover - structural
        """Re-attach a DEGRADED backend. Returns True if recovery succeeded.

        Implementations MUST be throttled internally — repeated calls
        within ``_RECOVERY_PROBE_INTERVAL_S`` are no-ops.
        """
        ...


# Registered backends use weak references so a backend object that gets
# replaced (the BOOT_FALLBACK → ACTIVE path replaces the instance) is
# garbage-collected normally. Strong references would leak per restart.
_registry_lock = threading.RLock()
_registry: list[weakref.ReferenceType[Any]] = []
_warm_hooks: list[Callable[[], None]] = []


def register_for_recovery(backend: RecoverableBackend) -> None:
    """Add ``backend`` to the recovery-monitor's worklist.

    Idempotent — re-registering the same instance is a no-op. Backends
    should call this from ``__init__`` so they participate in recovery
    from the moment they exist.
    """
    with _registry_lock:
        # GC dead refs while we're here.
        live = [ref for ref in _registry if ref() is not None]
        if any(ref() is backend for ref in live):
            _registry[:] = live
            return
        live.append(weakref.ref(backend))
        _registry[:] = live
        logger.info(
            "registered backend for recovery monitor",
            extra={"event": "backend_register", "alias": getattr(backend, "alias", "?")},
        )


def registered_backends() -> list[RecoverableBackend]:
    """Snapshot the live registered backends."""
    with _registry_lock:
        live = [ref() for ref in _registry]
        return [b for b in live if b is not None]


def register_warm_hook(hook: Callable[[], None]) -> None:
    """Add a callable to run after any DEGRADED backend re-attaches.

    Concrete consumers (auth-key prefix priming, bearer-token reprime)
    register here so a hot service doesn't take a cold-cache hit
    immediately after Valkey recovers.
    """
    with _registry_lock:
        if hook not in _warm_hooks:
            _warm_hooks.append(hook)


def _run_warm_hooks() -> None:
    for hook in list(_warm_hooks):
        try:
            hook()
        except Exception:  # noqa: BLE001 — warm hooks must not crash recovery
            logger.exception("warm hook failed during recovery")


def reset_backend(alias: str) -> bool:
    """Rebuild the backend identified by ``alias`` against live Valkey.

    Use for ``BOOT_FALLBACK`` recovery — the backend object is replaced,
    not flag-flipped. Returns True if a rebuild happened.

    Lazy-imports the relevant providers so this module stays
    dependency-light at import time.
    """
    if alias.startswith("cache:"):
        from core.resilience.cache.provider import reset_cache_backend  # noqa: PLC0415

        return reset_cache_backend(alias.removeprefix("cache:"))
    if alias.startswith("throttle:"):
        from core.resilience.throttles.provider import reset_throttle_backend  # noqa: PLC0415

        return reset_throttle_backend(alias.removeprefix("throttle:"))
    if alias.startswith("breaker:"):
        from core.resilience.circuit_breaker.provider import reset_breaker_registry  # noqa: PLC0415

        return reset_breaker_registry()
    logger.warning("reset_backend: unknown alias prefix %r", alias)
    return False


def attempt_recover_all() -> int:
    """Dispatch recovery for every non-ACTIVE registered backend.

    Returns the count of backends that successfully recovered. Called
    from the background monitor AND from the readiness probe.
    """
    recovered = 0
    for backend in registered_backends():
        try:
            health = backend.health
        except Exception:  # noqa: BLE001
            continue
        if health is BackendHealth.ACTIVE:
            continue
        if health.needs_object_rebuild:
            if reset_backend(backend.alias):
                recovered += 1
                continue
        # DEGRADED — flag flip via subsystem-internal probe.
        try:
            if backend.try_recover():
                recovered += 1
        except Exception:  # noqa: BLE001
            logger.exception("try_recover raised for %s", getattr(backend, "alias", "?"))
    if recovered:
        _run_warm_hooks()
    return recovered


class ValkeyRecoveryMonitor:
    """Background daemon thread that drives recovery when Valkey returns.

    The thread is a no-op while every registered backend is ACTIVE — it
    sleeps between cheap state checks instead of hammering Valkey. When
    something goes non-ACTIVE it transitions to active PING mode and
    waits for ``_STABLE_WINDOW_SUCCESSES`` consecutive successes before
    flipping any backend back.
    """

    def __init__(self, probe_interval_s: float = 10.0) -> None:
        self._probe_interval_s = probe_interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        # Successes since last failure — must reach _STABLE_WINDOW_SUCCESSES
        # before we trust Valkey enough to drive recovery.
        self._consecutive_successes = 0

    def start(self) -> None:
        """Idempotent — safe under autoreload, gunicorn worker fork, tests."""
        with self._start_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="valkey-recovery-monitor",
                daemon=True,
            )
            self._thread.start()
            logger.info("ValkeyRecoveryMonitor started")

    def stop(self, timeout: float = 1.0) -> None:
        """Used by tests and SIGTERM shutdown hooks."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)

    def _ping_valkey(self) -> bool:
        """Lightweight PING using the configured cache backend.

        Returns True on a clean round-trip. Lazy-imports django.core.cache
        so importing this module doesn't drag Django config into scope.
        """
        try:
            from django.core.cache import caches  # noqa: PLC0415

            caches["default"].set("_valkey_recovery_probe", "ok", timeout=5)
            return caches["default"].get("_valkey_recovery_probe") == "ok"
        except Exception:  # noqa: BLE001
            return False

    def _any_degraded(self) -> bool:
        for backend in registered_backends():
            try:
                if backend.health is not BackendHealth.ACTIVE:
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if not self._any_degraded():
                    # All ACTIVE — nothing to recover. Sleep cheap.
                    self._consecutive_successes = 0
                    self._stop.wait(self._probe_interval_s)
                    continue

                if self._ping_valkey():
                    self._consecutive_successes += 1
                else:
                    self._consecutive_successes = 0

                if self._consecutive_successes >= _STABLE_WINDOW_SUCCESSES:
                    recovered = attempt_recover_all()
                    if recovered:
                        logger.info(
                            "ValkeyRecoveryMonitor recovered %d backend(s)",
                            recovered,
                            extra={"event": "valkey_recovery", "recovered": recovered},
                        )
                    # Reset the window so we don't re-trigger on the next tick.
                    self._consecutive_successes = 0
            except Exception:  # noqa: BLE001 — never crash the monitor thread
                logger.exception("ValkeyRecoveryMonitor loop iteration failed")
            self._stop.wait(self._probe_interval_s)


# Module-level singleton — process-scoped per the thread-safety contract.
monitor = ValkeyRecoveryMonitor()


__all__ = [
    "RecoverableBackend",
    "ValkeyRecoveryMonitor",
    "attempt_recover_all",
    "monitor",
    "register_for_recovery",
    "register_warm_hook",
    "registered_backends",
    "reset_backend",
]
