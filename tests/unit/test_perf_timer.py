"""Unit tests for ``perf_timer`` / ``PerfTimer``."""

from __future__ import annotations

import time

from apps.core.utils.timing import perf_timer


def test_perf_timer_yields_float_elapsed() -> None:
    """``elapsed_ms`` is a float (sub-ms precision required for audit)."""
    with perf_timer() as t:
        pass
    assert isinstance(t.elapsed_ms, float)
    assert t.elapsed_ms >= 0.0


def test_perf_timer_mid_block_value_grows() -> None:
    """Reading ``elapsed_ms`` mid-block reflects time passing."""
    with perf_timer() as t:
        first = t.elapsed_ms
        time.sleep(0.005)
        second = t.elapsed_ms
        assert second >= first


def test_perf_timer_freezes_after_exit() -> None:
    """After exit, ``elapsed_ms`` is stable (does not keep growing)."""
    with perf_timer() as t:
        time.sleep(0.001)
    first = t.elapsed_ms
    time.sleep(0.005)
    assert t.elapsed_ms == first
