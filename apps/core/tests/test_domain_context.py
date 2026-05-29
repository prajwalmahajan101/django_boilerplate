"""Tests for ``domain_context`` and ``RequestContextFilter`` propagation.

Pin the contract that business identifiers stamped at the service-layer
boundary (push, assignment engine, remark task) appear on every nested
log record, including those emitted from helpers like
``make_http_request`` or ``SqlLeadsStrategy._run`` that don't know about
the identifiers themselves.
"""

from __future__ import annotations

import logging

from django.test import SimpleTestCase

from core.utils.logging import (
    RequestContextFilter,
    clear_request_context,
    domain_context,
    set_request_context,
)


class DomainContextPropagationTests(SimpleTestCase):
    def setUp(self) -> None:
        self.records: list[logging.LogRecord] = []
        self.handler = logging.Handler()
        self.handler.emit = self.records.append  # type: ignore[method-assign]
        self.handler.addFilter(RequestContextFilter())
        self.logger = logging.getLogger("test_domain_context")
        self.logger.handlers = [self.handler]
        self.logger.setLevel(logging.DEBUG)

    def tearDown(self) -> None:
        self.logger.handlers = []

    def test_partner_id_and_app_number_stamped_on_nested_records(self) -> None:
        with domain_context(partner_id=42, app_number="APP-001"):
            self.logger.info("inside")
        rec = self.records[-1]
        self.assertEqual(rec.partner_id, 42)
        self.assertEqual(rec.app_number, "APP-001")

    def test_context_cleared_after_exit(self) -> None:
        with domain_context(partner_id=42):
            pass
        self.logger.info("after")
        rec = self.records[-1]
        self.assertFalse(hasattr(rec, "partner_id"))

    def test_nested_contexts_compose_and_unwind(self) -> None:
        with domain_context(partner_id=1):
            with domain_context(app_number="A"):
                self.logger.info("inner")
            self.logger.info("outer")
        self.assertEqual(self.records[0].partner_id, 1)
        self.assertEqual(self.records[0].app_number, "A")
        self.assertEqual(self.records[1].partner_id, 1)
        self.assertFalse(hasattr(self.records[1], "app_number"))

    def test_request_id_filter_still_works(self) -> None:
        set_request_context("req-abc")
        try:
            self.logger.info("with request")
            self.assertEqual(self.records[-1].request_id, "req-abc")
        finally:
            clear_request_context()
