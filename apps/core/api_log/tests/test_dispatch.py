"""Unit tests for the dispatch orchestrator + decorators."""

from __future__ import annotations

import time

from core.api_log import factory
from core.api_log.dispatch import capture_and_dispatch
from core.api_log.models import Direction
from django.test import SimpleTestCase, override_settings


def _drain_queue() -> None:
    """Block until the api_log queue has executed every submitted item."""
    q = factory.get_apilog_queue()
    # The queue's internal ThreadPoolExecutor has no synchronous join;
    # poll task_done counters via the underlying Queue.
    q._queue.join()  # type: ignore[attr-defined]
    # Give the executor a moment to finish persisting after task_done.
    time.sleep(0.05)


@override_settings(API_LOG_BACKEND="noop")
class CaptureAndDispatchTests(SimpleTestCase):
    def setUp(self) -> None:
        factory.reset_for_tests()
        factory.init_repository()

    def test_success_path_returns_result_and_dispatches(self) -> None:
        def fn(x: int) -> int:
            return x * 2

        def build(result, exc, elapsed):
            return {
                "direction": Direction.INBOUND,
                "service_name": "t",
                "request_id": "r1",
                "method": "GET",
                "url": "/x",
                "status_code": 200 if exc is None else None,
                "duration_ms": elapsed,
                "request_headers": {},
                "request_body": None,
                "response_headers": {},
                "response_body": str(result) if result is not None else None,
                "error": None,
                "extra": {},
            }

        assert capture_and_dispatch(fn, (5,), {}, build) == 10
        _drain_queue()
        backend = factory.get_backend()
        self.assertEqual(len(backend.rows), 1)
        self.assertEqual(backend.rows[0]["status_code"], 200)
        self.assertEqual(backend.rows[0]["response_body"], "10")

    def test_error_path_dispatches_and_reraises(self) -> None:
        def fn() -> None:
            raise ValueError("boom")

        def build(result, exc, elapsed):
            return {
                "direction": Direction.INBOUND,
                "service_name": "t",
                "request_id": "r2",
                "method": "GET",
                "url": "/x",
                "status_code": None,
                "duration_ms": elapsed,
                "request_headers": {},
                "request_body": None,
                "response_headers": {},
                "response_body": None,
                "error": {"type": type(exc).__name__, "message": str(exc)} if exc else None,
                "extra": {},
            }

        with self.assertRaises(ValueError):
            capture_and_dispatch(fn, (), {}, build)
        _drain_queue()
        backend = factory.get_backend()
        last = backend.rows[-1]
        self.assertEqual(last["error"]["type"], "ValueError")
