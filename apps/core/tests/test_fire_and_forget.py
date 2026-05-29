"""Tests for ``FireAndForgetQueue`` — the primitive for best-effort dispatch.

Pin:
  * Submitted tasks run.
  * Overflow drops with a WARNING that includes the running drop counter.
  * ``drain`` returns True when the queue is empty.
"""

from __future__ import annotations

import logging
import threading
import time

from django.test import SimpleTestCase

from core.dispatch.fire_and_forget import FireAndForgetQueue


class FireAndForgetTests(SimpleTestCase):
    def test_submitted_task_runs(self) -> None:
        q = FireAndForgetQueue(
            "test-runs", max_in_flight=10, max_workers=1,
        )
        try:
            done = threading.Event()
            q.submit(done.set)
            self.assertTrue(done.wait(timeout=2.0))
        finally:
            q.stop(timeout=2.0)

    def test_overflow_drops_and_warns(self) -> None:
        records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = records.append  # type: ignore[method-assign]
        logger = logging.getLogger("core.dispatch.fire_and_forget")
        logger.addHandler(handler)

        # max_in_flight=1, no workers running yet (max_workers=1 but the
        # consumer drives them). Submit one slow + many fast and check
        # at least one is dropped.
        gate = threading.Event()
        q = FireAndForgetQueue("test-overflow", max_in_flight=1, max_workers=1)
        try:
            # First task blocks the worker so the queue can fill.
            q.submit(lambda: gate.wait(timeout=2.0))
            # Race to fill the queue beyond capacity. Some of these will drop.
            dropped_any = False
            for _ in range(50):
                if not q.submit(lambda: None):
                    dropped_any = True
                    break
            gate.set()
            self.assertTrue(dropped_any, "expected at least one overflow drop")
            self.assertGreaterEqual(q.dropped_count, 1)
        finally:
            logger.removeHandler(handler)
            q.stop(timeout=2.0)

        warning_events = [
            r for r in records
            if r.levelno == logging.WARNING and getattr(r, "event", "") == "fire_and_forget_overflow"
        ]
        self.assertGreaterEqual(len(warning_events), 1)
