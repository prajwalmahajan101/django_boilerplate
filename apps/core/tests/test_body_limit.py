"""Unit tests for ``ContentLengthLimitMiddleware``."""

from __future__ import annotations

import json

from django.core.exceptions import RequestDataTooBig
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from core.middleware.body_limit import ContentLengthLimitMiddleware


def _ok(_request):
    return HttpResponse("ok")


def _boom(_request):
    raise RequestDataTooBig()


class ContentLengthLimitMiddlewareTests(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()

    @override_settings(MAX_REQUEST_BODY_BYTES=100)
    def test_short_body_passes_through(self) -> None:
        mw = ContentLengthLimitMiddleware(_ok)
        request = self.factory.post("/api/v1/items/", data=b"x" * 50, content_type="application/octet-stream")
        response = mw(request)
        self.assertEqual(response.status_code, 200)

    @override_settings(MAX_REQUEST_BODY_BYTES=100)
    def test_oversize_declared_length_is_413(self) -> None:
        mw = ContentLengthLimitMiddleware(_ok)
        request = self.factory.post("/api/v1/items/", data=b"x" * 200, content_type="application/octet-stream")
        response = mw(request)
        self.assertEqual(response.status_code, 413)
        payload = json.loads(response.content)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["errors"][0]["code"], "REQUEST_BODY_TOO_LARGE")
        self.assertEqual(payload["errors"][0]["details"]["max_bytes"], 100)

    @override_settings(MAX_REQUEST_BODY_BYTES=0)
    def test_zero_disables_declared_check(self) -> None:
        mw = ContentLengthLimitMiddleware(_ok)
        request = self.factory.post("/api/v1/items/", data=b"x" * 200, content_type="application/octet-stream")
        response = mw(request)
        self.assertEqual(response.status_code, 200)

    @override_settings(MAX_REQUEST_BODY_BYTES=100)
    def test_request_data_too_big_translates_to_envelope(self) -> None:
        mw = ContentLengthLimitMiddleware(_boom)
        request = self.factory.get("/api/v1/items/")
        response = mw.process_exception(request, RequestDataTooBig())
        self.assertIsNotNone(response)
        assert response is not None  # narrow for mypy/pyright
        self.assertEqual(response.status_code, 413)
        payload = json.loads(response.content)
        self.assertEqual(payload["errors"][0]["code"], "REQUEST_BODY_TOO_LARGE")

    @override_settings(MAX_REQUEST_BODY_BYTES=100)
    def test_process_exception_ignores_unrelated_exceptions(self) -> None:
        mw = ContentLengthLimitMiddleware(_ok)
        request = self.factory.get("/api/v1/items/")
        self.assertIsNone(mw.process_exception(request, ValueError("nope")))

    @override_settings(MAX_REQUEST_BODY_BYTES=100)
    def test_malformed_content_length_passes_through(self) -> None:
        mw = ContentLengthLimitMiddleware(_ok)
        request = self.factory.get("/api/v1/items/")
        request.META["CONTENT_LENGTH"] = "not-a-number"
        response = mw(request)
        self.assertEqual(response.status_code, 200)
