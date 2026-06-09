"""Unit tests for ``PyBreakerCircuitBreaker`` and ``PyBreakerRegistry``.

Ports the FastAPI sibling's ``tests/unit/resilience/test_pybreaker.py``
against the sync Django impl — covers state transitions, excluded
exceptions, recovery timeout, and registry reuse.
"""

from __future__ import annotations

import time

from core.resilience.circuit_breaker.base import CircuitBreakerConfig
from core.resilience.circuit_breaker.pybreaker_impl import (
    PyBreakerCircuitBreaker,
    PyBreakerRegistry,
)


def _make(name: str = "test", **cfg) -> PyBreakerCircuitBreaker:
    config = CircuitBreakerConfig(
        failure_threshold=cfg.get("failure_threshold", 3),
        recovery_timeout=cfg.get("recovery_timeout", 60.0),
        excluded_exceptions=cfg.get("excluded_exceptions", ()),
    )
    return PyBreakerCircuitBreaker(breaker_name=name, config=config)


class TestPyBreakerCircuitBreaker:
    def test_initial_state_is_available(self) -> None:
        cb = _make()
        assert cb.is_available()
        assert cb.name == "test"
        assert cb.get_stats()["state"] == "closed"

    def test_trips_open_after_threshold(self) -> None:
        cb = _make(failure_threshold=3)
        for _ in range(3):
            cb.record_failure(RuntimeError("boom"))
        assert not cb.is_available()
        assert cb.get_stats()["state"] == "open"

    def test_excluded_exceptions_do_not_trip(self) -> None:
        cb = _make(failure_threshold=2, excluded_exceptions=(ValueError,))
        for _ in range(5):
            cb.record_failure(ValueError("ignored"))
        assert cb.is_available()
        assert cb.get_stats()["failure_count"] == 0

    def test_time_until_retry_decreases(self) -> None:
        cb = _make(failure_threshold=1, recovery_timeout=2.0)
        cb.record_failure(RuntimeError("boom"))
        first = cb.time_until_retry
        assert first > 0
        time.sleep(0.5)
        second = cb.time_until_retry
        assert second < first

    def test_time_until_retry_zero_when_closed(self) -> None:
        cb = _make()
        assert cb.time_until_retry == 0.0

    def test_reset_closes_open_breaker(self) -> None:
        cb = _make(failure_threshold=1)
        cb.record_failure(RuntimeError("boom"))
        assert not cb.is_available()
        cb.reset()
        assert cb.is_available()
        assert cb.get_stats()["state"] == "closed"

    def test_record_failure_in_open_state_is_noop(self) -> None:
        cb = _make(failure_threshold=1, recovery_timeout=60.0)
        cb.record_failure(RuntimeError("boom"))
        opened_at = cb._opened_at
        time.sleep(0.05)
        cb.record_failure(RuntimeError("boom"))
        assert cb._opened_at == opened_at  # not refreshed

    def test_get_stats_shape(self) -> None:
        cb = _make()
        stats = cb.get_stats()
        assert set(stats.keys()) >= {
            "name",
            "state",
            "failure_count",
            "time_until_retry",
            "backend",
        }
        assert stats["backend"] == "pybreaker"


class TestPyBreakerRegistry:
    def test_get_or_create_reuses_instance(self) -> None:
        reg = PyBreakerRegistry()
        a = reg.get_or_create("svc")
        b = reg.get_or_create("svc")
        assert a is b

    def test_distinct_names_yield_distinct_breakers(self) -> None:
        reg = PyBreakerRegistry()
        assert reg.get_or_create("s3") is not reg.get_or_create("ses")

    def test_remove_drops_breaker(self) -> None:
        reg = PyBreakerRegistry()
        reg.get_or_create("svc")
        reg.remove("svc")
        assert "svc" not in reg.get_all_stats()

    def test_reset_all_closes_each_breaker(self) -> None:
        reg = PyBreakerRegistry(CircuitBreakerConfig(failure_threshold=1))
        cb = reg.get_or_create("svc")
        cb.record_failure(RuntimeError("boom"))
        assert not cb.is_available()
        reg.reset_all()
        assert cb.is_available()

    def test_clear_drops_all_breakers(self) -> None:
        reg = PyBreakerRegistry()
        reg.get_or_create("a")
        reg.get_or_create("b")
        reg.clear()
        assert reg.get_all_stats() == {}
