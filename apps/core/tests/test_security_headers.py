"""Unit tests for ``SecurityHeadersMiddleware``."""

from __future__ import annotations

from unittest import mock

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from core.middleware.security_headers import (
    _BASE_HEADERS,
    _DOCS_CSP,
    SecurityHeadersMiddleware,
)


def _get_response(_request):
    return HttpResponse("ok")


class SecurityHeadersTests(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()

    def _build(self) -> SecurityHeadersMiddleware:
        with mock.patch.dict("os.environ", {"DJANGO_ENV": "prod"}):
            return SecurityHeadersMiddleware(_get_response)

    def test_base_headers_stamped(self) -> None:
        mw = self._build()
        response = mw(self.factory.get("/api/v1/items/"))
        for name, value in _BASE_HEADERS.items():
            self.assertEqual(response.headers[name], value)

    def test_hsts_in_prod(self) -> None:
        mw = self._build()
        response = mw(self.factory.get("/api/v1/items/"))
        self.assertIn("Strict-Transport-Security", response.headers)

    def test_hsts_skipped_in_dev_environment(self) -> None:
        with mock.patch.dict("os.environ", {"DJANGO_ENV": "local"}):
            mw = SecurityHeadersMiddleware(_get_response)
        response = mw(self.factory.get("/api/v1/items/"))
        self.assertNotIn("Strict-Transport-Security", response.headers)

    def test_docs_path_uses_relaxed_csp(self) -> None:
        mw = self._build()
        response = mw(self.factory.get("/api/schema/"))
        self.assertEqual(response.headers["Content-Security-Policy"], _DOCS_CSP)

    def test_non_docs_path_uses_strict_csp(self) -> None:
        mw = self._build()
        response = mw(self.factory.get("/api/v1/items/"))
        self.assertEqual(
            response.headers["Content-Security-Policy"],
            _BASE_HEADERS["Content-Security-Policy"],
        )

    def test_does_not_overwrite_pre_set_header(self) -> None:
        def upstream(_request):
            r = HttpResponse("ok")
            r.headers["X-Frame-Options"] = "SAMEORIGIN"
            return r

        with mock.patch.dict("os.environ", {"DJANGO_ENV": "prod"}):
            mw = SecurityHeadersMiddleware(upstream)
        response = mw(self.factory.get("/api/v1/items/"))
        self.assertEqual(response.headers["X-Frame-Options"], "SAMEORIGIN")

    @override_settings(SECURITY_HEADERS_ENABLED=False)
    def test_disabled_short_circuits(self) -> None:
        with mock.patch.dict("os.environ", {"DJANGO_ENV": "prod"}):
            mw = SecurityHeadersMiddleware(_get_response)
        response = mw(self.factory.get("/api/v1/items/"))
        self.assertNotIn("Strict-Transport-Security", response.headers)
        self.assertNotIn("Content-Security-Policy", response.headers)
