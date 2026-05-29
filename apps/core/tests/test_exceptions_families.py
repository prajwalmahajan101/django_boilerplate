"""Unit tests for the new typed exception families.

Covers:
  * ``APIError`` — status_code override, response_body + details merge.
  * Auth family — status_code class attribute, error_code stability.
  * ``ValidationError`` — field surfaced in envelope.
  * ``RateLimitError`` — header dict + details payload.
  * ``utils`` — duck-typed normalize_outbound_exception.

These exceptions declare ``status_code`` as a class attribute, so the
DRF handler picks it up via the ``hasattr(exc, "status_code")`` short
circuit without needing ``register_exception_mapping`` calls.
"""

from __future__ import annotations

from core.exceptions.api import APIError
from core.exceptions.auth import (
    APIKeyRevokedError,
    AuthenticationFailedError,
    PermissionDeniedError,
    TokenExpiredError,
    TokenInvalidError,
    TokenRevokedError,
)
from core.exceptions.handler import api_exception_handler
from core.exceptions.rate_limit import RateLimitError
from core.exceptions.utils import (
    exception_response_payload,
    exception_wire_status,
    normalize_outbound_exception,
)
from core.exceptions.validation import ValidationError
from django.test import SimpleTestCase


class APIErrorTest(SimpleTestCase):
    def test_default_status_502(self):
        response = api_exception_handler(APIError("upstream down"), context={})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data["errors"][0]["code"], "API_ERROR")

    def test_per_instance_status_override(self):
        exc = APIError("not found", status_code=404)
        response = api_exception_handler(exc, context={})
        self.assertEqual(response.status_code, 404)

    def test_details_merge_with_response_body(self):
        exc = APIError(
            "bad gateway",
            status_code=502,
            response_body='{"err":"x"}',
            details={"upstream": "partner-a"},
        )
        details = exc.get_details()
        self.assertEqual(details["upstream"], "partner-a")
        self.assertEqual(details["response_body"], '{"err":"x"}')
        self.assertEqual(details["status_code"], 502)


class AuthFamilyTest(SimpleTestCase):
    def test_authentication_failed_maps_to_401(self):
        response = api_exception_handler(AuthenticationFailedError(), context={})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["errors"][0]["code"], "AUTHENTICATION_FAILED")

    def test_api_key_revoked_inherits_401(self):
        response = api_exception_handler(APIKeyRevokedError(), context={})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["errors"][0]["code"], "API_KEY_REVOKED")

    def test_permission_denied_maps_to_403(self):
        response = api_exception_handler(PermissionDeniedError(), context={})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["errors"][0]["code"], "PERMISSION_DENIED")

    def test_token_subclasses_distinct_codes(self):
        for exc_cls, code in (
            (TokenExpiredError, "TOKEN_EXPIRED"),
            (TokenInvalidError, "TOKEN_INVALID"),
            (TokenRevokedError, "TOKEN_REVOKED"),
        ):
            response = api_exception_handler(exc_cls(), context={})
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.data["errors"][0]["code"], code)

    def test_isinstance_authentication_failed(self):
        # All token subclasses are AuthenticationFailedError so a single
        # ``except`` block catches them all.
        for exc_cls in (
            TokenExpiredError,
            TokenInvalidError,
            TokenRevokedError,
            APIKeyRevokedError,
        ):
            self.assertTrue(issubclass(exc_cls, AuthenticationFailedError))


class ValidationErrorTest(SimpleTestCase):
    def test_field_surfaces_in_envelope(self):
        exc = ValidationError("must be positive", field="amount")
        response = api_exception_handler(exc, context={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["errors"][0]["field"], "amount")
        self.assertEqual(response.data["errors"][0]["code"], "VALIDATION_ERROR")

    def test_details_passed_through(self):
        exc = ValidationError(
            "bad transition", field="state", details={"from": "draft", "to": "shipped"}
        )
        envelope = exc.to_error_dict()
        self.assertEqual(envelope["details"], {"from": "draft", "to": "shipped"})

    def test_empty_details_becomes_none(self):
        exc = ValidationError("invalid")
        self.assertIsNone(exc.to_error_dict()["details"])


class RateLimitErrorTest(SimpleTestCase):
    def test_status_429_and_details(self):
        exc = RateLimitError(
            limit=10, window_seconds=60, retry_after=15, remaining=0, reset_at=1700000000
        )
        response = api_exception_handler(exc, context={})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data["errors"][0]["code"], "RATE_LIMITED")
        self.assertEqual(
            response.data["errors"][0]["details"],
            {
                "limit": 10,
                "window_seconds": 60,
                "retry_after": 15,
                "remaining": 0,
                "reset_at": 1700000000,
            },
        )

    def test_response_headers_shape(self):
        exc = RateLimitError(limit=5, window_seconds=10, retry_after=3, remaining=2, reset_at=42)
        self.assertEqual(
            exc.response_headers(),
            {
                "Retry-After": "3",
                "X-RateLimit-Limit": "5",
                "X-RateLimit-Remaining": "2",
                "X-RateLimit-Reset": "42",
            },
        )

    def test_retry_after_floored_to_one(self):
        exc = RateLimitError(limit=1, window_seconds=1, retry_after=0)
        self.assertEqual(exc.retry_after, 1)


class NormalizeOutboundExceptionTest(SimpleTestCase):
    def test_api_error_wire_status_and_payload(self):
        exc = APIError("nope", status_code=503, response_body='{"x":1}')
        normalized = normalize_outbound_exception(exc)
        self.assertEqual(normalized["status_code"], 503)
        self.assertEqual(normalized["response_body"], {"x": 1})

    def test_response_attr_wins_over_response_body(self):
        class FakeExc(Exception):
            response = {"already": "parsed"}
            response_body = '{"ignored":true}'
            response_status_code = 502

        self.assertEqual(exception_response_payload(FakeExc()), {"already": "parsed"})
        self.assertEqual(exception_wire_status(FakeExc()), 502)

    def test_fallback_to_details_then_502(self):
        class FakeExc(Exception):
            details = {"hint": "ok"}

        self.assertEqual(exception_response_payload(FakeExc()), {"hint": "ok"})
        self.assertEqual(exception_wire_status(FakeExc()), 502)

    def test_unparseable_body_falls_through(self):
        class FakeExc(Exception):
            response_body = "<html>not json</html>"
            details = {"upstream": "partner"}

        self.assertEqual(exception_response_payload(FakeExc()), {"upstream": "partner"})
