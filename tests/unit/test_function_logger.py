"""Unit tests for ``@log_function``."""

from __future__ import annotations

import asyncio
import logging

import pytest

from apps.core.utils.function_logger import (
    _summarize,
    is_function_logging_enabled,
    log_function,
)


def test_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FUNCTION_LOGGING_ENABLED", raising=False)
    assert is_function_logging_enabled() is False


def test_enabled_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FUNCTION_LOGGING_ENABLED", "true")
    assert is_function_logging_enabled() is True


def test_summarize_collections() -> None:
    assert _summarize({"a": 1, "b": 2}) == "<dict with 2 keys>"
    assert _summarize([1, 2, 3]) == "<list with 3 items>"
    assert _summarize((1, 2)) == "<tuple with 2 items>"


def test_summarize_truncates_long_strings() -> None:
    out = _summarize("x" * 500)
    assert out.endswith("...")
    assert len(out) == 203


def test_sync_decorator_returns_result_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FUNCTION_LOGGING_ENABLED", raising=False)

    @log_function()
    def add(a: int, b: int) -> int:
        return a + b

    assert add(2, 3) == 5


def test_sync_decorator_logs_entry_exit_when_enabled(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("FUNCTION_LOGGING_ENABLED", "true")

    @log_function()
    def add(a: int, b: int) -> int:
        return a + b

    with caplog.at_level(logging.DEBUG):
        add(2, 3)

    events = [r.__dict__.get("event") for r in caplog.records]
    assert "function_enter" in events
    assert "function_exit" in events


def test_error_emitted_even_when_disabled(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("FUNCTION_LOGGING_ENABLED", raising=False)

    @log_function()
    def boom() -> None:
        raise ValueError("nope")

    with caplog.at_level(logging.ERROR), pytest.raises(ValueError):
        boom()

    error_events = [r for r in caplog.records if r.__dict__.get("event") == "function_error"]
    assert len(error_events) == 1


def test_async_decorator_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FUNCTION_LOGGING_ENABLED", "true")

    @log_function()
    async def aadd(a: int, b: int) -> int:
        await asyncio.sleep(0)
        return a + b

    assert asyncio.run(aadd(4, 5)) == 9
