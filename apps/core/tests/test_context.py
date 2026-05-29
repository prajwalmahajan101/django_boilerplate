"""Unit tests for ``core.context`` — request-ID ContextVar plumbing.

Confirms:
  * set/get/clear roundtrip.
  * Token-based reset restores the prior value (nested set).
  * Threads see their own copy (gthread isolation contract).
"""

from __future__ import annotations

import threading

from core.context import (
    clear_request_context,
    get_request_id,
    set_request_context,
)
from django.test import SimpleTestCase


class ContextRoundtripTest(SimpleTestCase):
    def test_set_get_clear(self):
        self.assertIsNone(get_request_id())
        token = set_request_context("abc-123")
        try:
            self.assertEqual(get_request_id(), "abc-123")
        finally:
            clear_request_context(token)
        self.assertIsNone(get_request_id())

    def test_nested_set_restores_outer_on_reset(self):
        outer = set_request_context("outer-id")
        try:
            inner = set_request_context("inner-id")
            try:
                self.assertEqual(get_request_id(), "inner-id")
            finally:
                clear_request_context(inner)
            self.assertEqual(get_request_id(), "outer-id")
        finally:
            clear_request_context(outer)
        self.assertIsNone(get_request_id())

    def test_clear_without_token_resets_to_none(self):
        set_request_context("dangling")
        clear_request_context()
        self.assertIsNone(get_request_id())


class ContextThreadIsolationTest(SimpleTestCase):
    def test_threads_get_independent_copies(self):
        token = set_request_context("main-thread")
        seen: dict[str, str | None] = {}
        ready = threading.Event()

        def worker() -> None:
            seen["before_set"] = get_request_id()
            set_request_context("worker-thread")
            seen["after_set"] = get_request_id()
            ready.set()

        t = threading.Thread(target=worker)
        t.start()
        ready.wait(timeout=2)
        t.join(timeout=2)
        # Main thread still sees its own value — worker's set did not bleed.
        self.assertEqual(get_request_id(), "main-thread")
        # Worker started with no inherited value (Thread doesn't copy ContextVars).
        self.assertIsNone(seen["before_set"])
        self.assertEqual(seen["after_set"], "worker-thread")
        clear_request_context(token)


class LegacyLoggingShimTest(SimpleTestCase):
    """The old ``core.utils.logging.set_request_context`` signature
    (no token return) must continue to work for callers that still
    use it — middleware moved over but other code may not have."""

    def test_legacy_shim_still_sets_and_clears(self):
        from core.utils.logging import (
            clear_request_context as legacy_clear,
        )
        from core.utils.logging import (
            set_request_context as legacy_set,
        )

        legacy_set("legacy-id")
        self.assertEqual(get_request_id(), "legacy-id")
        legacy_clear()
        self.assertIsNone(get_request_id())
