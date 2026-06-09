"""Pybreaker-based circuit breaker implementation (in-memory, per-process).

Wraps the pybreaker library behind the BaseCircuitBreaker interface.
Used as the fallback when Valkey is unavailable.

Note: State is per-process. In a multi-worker deployment (gunicorn prefork),
each worker maintains independent breaker state.
"""

from __future__ import annotations

import contextlib
import logging
from threading import RLock
from typing import Any

import pybreaker
from core.resilience.circuit_breaker.base import (
    BaseCircuitBreaker,
    BaseCircuitBreakerRegistry,
    CircuitBreakerConfig,
)

logger = logging.getLogger(__name__)


class PyBreakerCircuitBreaker(BaseCircuitBreaker):
    """Circuit breaker backed by pybreaker (in-memory).

    Wraps a ``pybreaker.CircuitBreaker`` instance and adapts it to
    the ``BaseCircuitBreaker`` interface.
    """

    def __init__(self, breaker_name: str, config: CircuitBreakerConfig) -> None:
        self._name = breaker_name
        self._config = config
        self._opened_at: float = 0.0
        self._breaker = pybreaker.CircuitBreaker(
            fail_max=config.failure_threshold,
            reset_timeout=config.recovery_timeout,
            name=breaker_name,
            exclude=list(config.excluded_exceptions),
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def time_until_retry(self) -> float:
        if self._breaker.current_state != "open":
            return 0.0
        import time

        if self._opened_at:
            elapsed = time.time() - self._opened_at
            return max(0.0, self._breaker.reset_timeout - elapsed)
        return self._breaker.reset_timeout

    def is_available(self) -> bool:
        return self._breaker.current_state != "open"

    def record_success(self) -> None:
        # Manipulate pybreaker state directly to avoid semantic issues:
        # - In OPEN state, .call() raises CircuitBreakerError (success dropped)
        # - In HALF_OPEN state, .call() double-counts the success
        state = self._breaker.current_state
        if state == "open":
            # Cannot record success while open — the breaker must
            # transition to half-open first via its own timeout.
            return
        if state == "half-open":
            # In half-open, a success should drive toward closing.
            # Use .call() with a no-op — this is the one correct case.
            with contextlib.suppress(pybreaker.CircuitBreakerError):
                self._breaker.call(lambda: None)
            if self._breaker.current_state == "closed":
                self._opened_at = 0.0
            return
        # In closed state, just reset the fail counter.
        self._breaker._fail_counter = 0

    def record_failure(self, exc: Exception | None = None) -> None:
        if exc is not None and isinstance(exc, self._config.excluded_exceptions):
            return

        state = self._breaker.current_state
        if state == "open":
            # Breaker is already open; pybreaker's internal timer is the
            # source of truth for the half-open transition. Do NOT refresh
            # self._opened_at — doing so would drift from pybreaker's timer
            # and make time_until_retry disagree with is_available().
            return

        # Drive a failure through pybreaker by calling a function that raises.
        # Synthetic failures (exc is None) raise ServiceUnavailableError so the
        # whole resilience module speaks the typed exception hierarchy — the
        # exception is consumed by pybreaker.call() below and never escapes.
        from core.exceptions.infrastructure import ServiceUnavailableError

        def _fail():
            raise exc if exc is not None else ServiceUnavailableError(self._name)

        try:
            self._breaker.call(_fail)
        except pybreaker.CircuitBreakerError:
            pass
        except Exception:
            pass  # The exception we just raised — expected

        # Track when the breaker transitions to open
        if self._breaker.current_state == "open":
            import time

            self._opened_at = time.time()

    def reset(self) -> None:
        self._breaker.close()
        self._opened_at = 0.0

    def get_stats(self) -> dict[str, Any]:
        return {
            "name": self._name,
            "state": self._breaker.current_state,
            "failure_count": self._breaker.fail_counter,
            "success_count": self._breaker.success_counter,
            "time_until_retry": self.time_until_retry,
            "backend": "pybreaker",
        }


class PyBreakerRegistry(BaseCircuitBreakerRegistry):
    """Registry for pybreaker-based circuit breakers."""

    def __init__(self, default_config: CircuitBreakerConfig | None = None) -> None:
        self._breakers: dict[str, PyBreakerCircuitBreaker] = {}
        self._lock = RLock()
        self._default_config = default_config or CircuitBreakerConfig()

    def get_or_create(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ) -> PyBreakerCircuitBreaker:
        breaker = self._breakers.get(name)
        if breaker is not None:
            return breaker

        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = PyBreakerCircuitBreaker(
                    breaker_name=name,
                    config=config or self._default_config,
                )
            return self._breakers[name]

    def remove(self, name: str) -> None:
        with self._lock:
            self._breakers.pop(name, None)

    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {name: cb.get_stats() for name, cb in self._breakers.items()}

    def reset_all(self) -> None:
        with self._lock:
            for breaker in self._breakers.values():
                breaker.reset()

    def clear(self) -> None:
        with self._lock:
            self._breakers.clear()
