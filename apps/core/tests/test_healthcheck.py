"""Unit tests for composable health-check primitives."""

from __future__ import annotations

from core.lifecycle.healthcheck import HealthCheckResult, run_checks


def _ok() -> HealthCheckResult:
    return HealthCheckResult(name="ok", healthy=True, detail="up")


def _bad() -> HealthCheckResult:
    return HealthCheckResult(name="bad", healthy=False, detail="down")


def _raises() -> HealthCheckResult:
    raise RuntimeError("kaboom")


def test_empty_check_list_is_healthy() -> None:
    results, healthy = run_checks([])
    assert results == []
    assert healthy is True


def test_all_pass_is_healthy() -> None:
    results, healthy = run_checks([_ok, _ok])
    assert healthy is True
    assert len(results) == 2


def test_any_fail_is_unhealthy() -> None:
    _, healthy = run_checks([_ok, _bad])
    assert healthy is False


def test_raising_probe_is_caught_and_recorded_as_unhealthy() -> None:
    results, healthy = run_checks([_ok, _raises])
    assert healthy is False
    assert results[1].healthy is False
    assert "RuntimeError" in results[1].detail
