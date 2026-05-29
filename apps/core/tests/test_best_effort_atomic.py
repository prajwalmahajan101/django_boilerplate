"""Tests for ``core.db.best_effort_atomic``."""

from __future__ import annotations

import logging

from django.test import TestCase

from core.db import best_effort_atomic


class BestEffortAtomicTests(TestCase):
    def test_success_runs_block(self) -> None:
        ran = []
        with best_effort_atomic("noop"):
            ran.append(True)
        self.assertEqual(ran, [True])

    def test_exception_is_swallowed(self) -> None:
        with best_effort_atomic("noop"):
            raise RuntimeError("boom")

    def test_exception_logged_with_label(self) -> None:
        log = logging.getLogger("test.best_effort_atomic")
        with self.assertLogs(log, level="WARNING") as captured:
            with best_effort_atomic("persist audit row", logger=log):
                raise RuntimeError("boom")
        self.assertTrue(
            any("failed to persist audit row" in m for m in captured.output)
        )
