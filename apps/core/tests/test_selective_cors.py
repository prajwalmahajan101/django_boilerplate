"""Unit tests for ``SelectiveCORSMiddleware``."""

from __future__ import annotations

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from core.middleware.selective_cors import SelectiveCORSMiddleware


def _ok(_request):
    return HttpResponse("ok")


class SelectiveCORSTests(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()

    @override_settings(
        CORS_EXCLUDED_PREFIXES=("/webhooks/",),
        CORS_ALLOWED_ORIGINS=["https://example.com"],
        CORS_ALLOW_CREDENTIALS=False,
    )
    def test_excluded_prefix_skips_cors_headers(self) -> None:
        mw = SelectiveCORSMiddleware(_ok)
        request = self.factory.get(
            "/webhooks/stripe/", HTTP_ORIGIN="https://example.com"
        )
        response = mw(request)
        # CorsMiddleware would have added the header; we bypassed it.
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    @override_settings(
        CORS_EXCLUDED_PREFIXES=("/webhooks/",),
        CORS_ALLOW_ALL_ORIGINS=True,
        CORS_ALLOWED_ORIGINS=[],
        CORS_ALLOW_CREDENTIALS=False,
    )
    def test_non_excluded_path_delegates_to_corsmiddleware(self) -> None:
        mw = SelectiveCORSMiddleware(_ok)
        request = self.factory.get(
            "/api/v1/items/", HTTP_ORIGIN="https://example.com"
        )
        response = mw(request)
        self.assertIn("Access-Control-Allow-Origin", response.headers)

    @override_settings(CORS_EXCLUDED_PREFIXES=())
    def test_no_excluded_prefixes_behaves_as_passthrough(self) -> None:
        mw = SelectiveCORSMiddleware(_ok)
        request = self.factory.get("/api/v1/items/")
        response = mw(request)
        self.assertEqual(response.status_code, 200)
