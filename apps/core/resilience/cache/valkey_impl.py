"""Valkey-backed cache implementation.

Wraps Django's cache framework (configured with django-valkey) and provides
fail-open behavior: if Valkey is unreachable, operations fall back to an
InMemoryCacheBackend so the application degrades gracefully rather than crashing.
"""

from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Any

from core.resilience.cache.base import BaseCacheBackend
from core.resilience.cache.inmemory_impl import InMemoryCacheBackend
from core.resilience.health import BackendHealth

logger = logging.getLogger(__name__)

_RECOVERY_PROBE_INTERVAL_S = 30.0


class ValkeyCacheBackend(BaseCacheBackend):
    """Valkey-backed cache with fail-open to in-memory fallback.

    Uses Django's cache framework (``django.core.cache.caches``) configured
    with a Valkey backend. If any operation fails, it transparently falls
    back to an InMemoryCacheBackend for that operation.

    Exposes ``health`` and ``try_recover`` so the recovery monitor can
    flip a DEGRADED backend back to ACTIVE without restarting workers.
    A backend constructed without a live Valkey client is BOOT_FALLBACK
    and can only be recovered by ``reset_cache_backend(alias)``.
    """

    def __init__(self, cache_alias: str = "default") -> None:
        self._cache_alias = cache_alias
        self.alias = f"cache:{cache_alias}"
        self._cache = None
        self._fallback = InMemoryCacheBackend(location=f"valkey-fallback-{cache_alias}")
        self._using_fallback = False
        self._fallback_lock = Lock()
        self._boot_fallback = False
        self._last_recovery_attempt = 0.0

        try:
            from django.core.cache import caches

            self._cache = caches[cache_alias]
            # Probe connectivity
            self._cache.set("_valkey_cache_probe", "ok", timeout=5)
            logger.info("Valkey cache backend initialized (alias=%s)", cache_alias)
        except Exception as e:
            logger.warning(
                "Failed to initialize Valkey cache backend (alias=%s), "
                "falling back to in-memory: %s",
                cache_alias,
                e,
            )
            self._cache = None
            self._using_fallback = True
            self._boot_fallback = True

        # Register with the recovery monitor whether we started healthy
        # or in BOOT_FALLBACK — registration is idempotent and a healthy
        # backend simply has nothing to recover.
        try:
            from core.resilience.recovery import register_for_recovery

            register_for_recovery(self)
        except Exception:
            logger.exception("cache backend failed to register for recovery")

    @property
    def backend_name(self) -> str:
        if self._using_fallback:
            return "inmemory-fallback"
        return "valkey"

    @property
    def health(self) -> BackendHealth:
        """Return the current BackendHealth state.

        BOOT_FALLBACK > DEGRADED > ACTIVE in severity; the most-pessimistic
        state wins so the recovery monitor takes the right path.
        """
        if self._boot_fallback:
            return BackendHealth.BOOT_FALLBACK
        if self._using_fallback:
            return BackendHealth.DEGRADED
        return BackendHealth.ACTIVE

    def try_recover(self) -> bool:
        """Attempt to flip a DEGRADED backend back to ACTIVE.

        Throttled internally to once per ``_RECOVERY_PROBE_INTERVAL_S`` so
        the in-call probe path (degraded operation calls this) and the
        background-monitor path (every probe tick) can both safely call it.

        Returns True if the backend was DEGRADED and is now ACTIVE.
        Always False for BOOT_FALLBACK — that recovery path is
        ``reset_cache_backend``, not a flag flip.
        """
        if self._boot_fallback or self._cache is None:
            return False
        if not self._using_fallback:
            return False

        now = time.monotonic()
        if now - self._last_recovery_attempt < _RECOVERY_PROBE_INTERVAL_S:
            return False
        self._last_recovery_attempt = now

        try:
            self._cache.set("_valkey_recovery_probe", "ok", timeout=5)
            if self._cache.get("_valkey_recovery_probe") != "ok":
                return False
        except Exception as e:
            logger.info(
                "cache try_recover failed for %s: %s",
                self.alias,
                e,
            )
            return False

        with self._fallback_lock:
            self._using_fallback = False
        logger.info(
            "cache backend recovered",
            extra={"event": "cache_recovered", "alias": self.alias},
        )
        return True

    def _with_fallback(self, operation: str, func, *args, **kwargs) -> Any:
        """Execute func on Valkey, fall back to in-memory on error."""
        if self._cache is not None:
            try:
                result = func(*args, **kwargs)
                with self._fallback_lock:
                    self._using_fallback = False
                return result
            except Exception as e:
                with self._fallback_lock:
                    if not self._using_fallback:
                        logger.warning(
                            "Valkey cache %s failed, falling back to in-memory: %s",
                            operation,
                            e,
                        )
                        self._using_fallback = True

        # Fallback to in-memory
        fallback_func = getattr(self._fallback, operation)
        return fallback_func(*args, **kwargs)

    def get(self, key: str) -> Any | None:
        return (
            self._with_fallback("get", self._cache.get, key)
            if self._cache is not None
            else self._fallback.get(key)
        )

    def set(self, key: str, value: Any, timeout: int | None = None) -> None:
        if self._cache is not None:
            self._with_fallback("set", self._cache.set, key, value, timeout=timeout)
        else:
            self._fallback.set(key, value, timeout=timeout)

    def delete(self, key: str) -> None:
        if self._cache is not None:
            self._with_fallback("delete", self._cache.delete, key)
        else:
            self._fallback.delete(key)

    def incr(self, key: str) -> int:
        # Inlined instead of routed through _with_fallback so a missing-key
        # ValueError (the documented raise path for incr) does not flip the
        # backend into fallback mode. Only real Valkey failures should trip
        # the _using_fallback flag.
        if self._cache is None:
            return self._fallback.incr(key)
        try:
            result = self._cache.incr(key)
        except ValueError:
            raise  # Missing key — caller's contract, not a Valkey failure.
        except Exception as e:
            with self._fallback_lock:
                if not self._using_fallback:
                    logger.warning(
                        "Valkey cache incr failed, falling back to in-memory: %s",
                        e,
                    )
                    self._using_fallback = True
            return self._fallback.incr(key)

        with self._fallback_lock:
            self._using_fallback = False
        return result

    def add(self, key: str, value: Any, timeout: int | None = None) -> bool:
        return (
            self._with_fallback("add", self._cache.add, key, value, timeout=timeout)
            if self._cache is not None
            else self._fallback.add(key, value, timeout=timeout)
        )

    def clear(self) -> None:
        if self._cache is not None:
            self._with_fallback("clear", self._cache.clear)
        else:
            self._fallback.clear()

    def is_healthy(self) -> bool:
        if self._cache is None:
            return False
        try:
            self._cache.set("_health_check", "ok", timeout=5)
            return self._cache.get("_health_check") == "ok"
        except Exception:
            return False
