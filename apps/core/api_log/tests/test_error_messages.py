"""Tests for ``build_error_message``."""

from __future__ import annotations

from core.api_log.error_messages import build_error_message
from core.exceptions.infrastructure import ServiceUnavailableError
from django.test import SimpleTestCase


class BuildErrorMessageTests(SimpleTestCase):
    def test_bare_exception(self) -> None:
        msg = build_error_message(RuntimeError("boom"))
        self.assertIn("RuntimeError", msg)
        self.assertIn("boom", msg)

    def test_typed_exception_includes_status_and_details(self) -> None:
        exc = ServiceUnavailableError("s3", status_code=503)
        msg = build_error_message(exc)
        self.assertIn("status_code=503", msg)
        self.assertIn("service_name", msg)

    def test_typed_exception_without_explicit_status_still_includes_details(self) -> None:
        exc = ServiceUnavailableError("partner_api")
        msg = build_error_message(exc)
        self.assertIn("ServiceUnavailableError", msg)
        self.assertIn("partner_api", msg)
