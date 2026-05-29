"""Unit tests for ``InMemoryThrottle`` and ``parse_rate``."""

from __future__ import annotations

import time

import pytest

from apps.core.resilience.throttles.memory_impl import InMemoryThrottle
from apps.core.resilience.throttles.scopes import parse_rate


def test_parse_rate_simple() -> None:
    assert parse_rate("100/min") == (100, 60)
    assert parse_rate("5/sec") == (5, 1)
    assert parse_rate("1000/hour") == (1000, 3600)


def test_parse_rate_short_unit() -> None:
    assert parse_rate("10/s") == (10, 1)
    assert parse_rate("10/m") == (10, 60)
    assert parse_rate("10/h") == (10, 3600)
    assert parse_rate("10/d") == (10, 86_400)


def test_parse_rate_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        parse_rate("not-a-rate")
    with pytest.raises(ValueError):
        parse_rate("5/year")


def test_throttle_allows_under_limit() -> None:
    t = InMemoryThrottle()
    for _ in range(3):
        r = t.check("k", limit=5, window_seconds=10)
        assert r.allowed is True
    r = t.check("k", limit=5, window_seconds=10)
    assert r.remaining == 1


def test_throttle_denies_over_limit() -> None:
    t = InMemoryThrottle()
    for _ in range(5):
        t.check("k", limit=5, window_seconds=60)
    r = t.check("k", limit=5, window_seconds=60)
    assert r.allowed is False
    assert r.remaining == 0
    assert r.retry_after > 0


def test_throttle_isolates_identifiers() -> None:
    t = InMemoryThrottle()
    for _ in range(5):
        t.check("a", limit=5, window_seconds=60)
    assert t.check("b", limit=5, window_seconds=60).allowed is True


def test_throttle_window_slides() -> None:
    t = InMemoryThrottle()
    for _ in range(3):
        t.check("k", limit=3, window_seconds=1)
    time.sleep(1.1)
    assert t.check("k", limit=3, window_seconds=1).allowed is True


def test_backend_name() -> None:
    assert InMemoryThrottle().backend_name == "memory"
