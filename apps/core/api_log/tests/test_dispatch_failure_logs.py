"""Failure-path logs from ``capture_and_dispatch`` carry correlation extras.

ISSUE-021 — every ``logger.exception`` call on the dispatch failure
paths includes ``service_name`` / ``direction`` / ``request_id`` /
``log_id``, so tracing a "lost audit row" back to the originating
service is a ``grep``, not a guess.
"""

from __future__ import annotations

import logging

import pytest
from core.api_log import dispatch as dispatch_mod
from core.api_log import factory
from core.api_log.models import Direction
from core.utils.logging import _request_id_var
from django.test import override_settings


def _trivial_row(*_args, **_kwargs) -> dict:
    return {
        "direction": Direction.INBOUND,
        "service_name": "t",
        "request_id": "r",
        "method": "GET",
        "url": "/",
        "status_code": 200,
        "duration_ms": 0.0,
        "request_headers": {},
        "request_body": None,
        "response_headers": {},
        "response_body": None,
        "error": None,
        "extra": {},
    }


def _bad_builder(*_args, **_kwargs) -> dict:
    raise RuntimeError("builder boom")


def _assert_correlation(
    record: logging.LogRecord,
    *,
    service_name: str,
    direction: Direction,
) -> None:
    assert getattr(record, "service_name", None) == service_name
    assert getattr(record, "direction", None) == direction
    log_id = getattr(record, "log_id", None)
    assert isinstance(log_id, str) and log_id, "log_id missing or empty"
    # request_id key is present (may be None when no middleware set one).
    assert hasattr(record, "request_id")


@override_settings(API_LOG_BACKEND="noop")
def test_queue_failure_logs_carry_correlation(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    factory.reset_for_tests()
    factory.init_repository()
    monkeypatch.setattr(
        factory, "get_apilog_queue", lambda: (_ for _ in ()).throw(RuntimeError("q boom"))
    )
    token = _request_id_var.set("req-abc")
    try:
        with caplog.at_level(logging.ERROR, logger="core.api_log.dispatch"):
            result = dispatch_mod.capture_and_dispatch(
                lambda: "ok",
                (),
                {},
                _trivial_row,
                service_name="svc-a",
                direction=Direction.INBOUND,
            )
    finally:
        _request_id_var.reset(token)

    assert result == "ok"
    matching = [r for r in caplog.records if "api_log dispatch failed" in r.getMessage()]
    assert matching, "expected dispatch failure log"
    _assert_correlation(matching[0], service_name="svc-a", direction=Direction.INBOUND)
    assert matching[0].request_id == "req-abc"


@override_settings(API_LOG_BACKEND="noop")
def test_success_path_builder_failure_logs_carry_correlation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    factory.reset_for_tests()
    factory.init_repository()
    with caplog.at_level(logging.ERROR, logger="core.api_log.dispatch"):
        result = dispatch_mod.capture_and_dispatch(
            lambda: "ok",
            (),
            {},
            _bad_builder,
            service_name="svc-b",
            direction=Direction.OUTBOUND,
        )
    assert result == "ok"
    matching = [
        r for r in caplog.records if "api_log build_row failed (success path)" in r.getMessage()
    ]
    assert matching, "expected build_row success-path failure log"
    _assert_correlation(matching[0], service_name="svc-b", direction=Direction.OUTBOUND)


@override_settings(API_LOG_BACKEND="noop")
def test_error_path_builder_failure_logs_carry_correlation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    factory.reset_for_tests()
    factory.init_repository()

    def fn() -> None:
        raise ValueError("call boom")

    with caplog.at_level(logging.ERROR, logger="core.api_log.dispatch"):
        with pytest.raises(ValueError):
            dispatch_mod.capture_and_dispatch(
                fn,
                (),
                {},
                _bad_builder,
                service_name="svc-c",
                direction=Direction.INBOUND,
            )
    matching = [
        r for r in caplog.records if "api_log build_row failed (error path)" in r.getMessage()
    ]
    assert matching, "expected build_row error-path failure log"
    _assert_correlation(matching[0], service_name="svc-c", direction=Direction.INBOUND)
