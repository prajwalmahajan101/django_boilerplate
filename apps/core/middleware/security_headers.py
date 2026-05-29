"""``SecurityHeadersMiddleware`` — defensive response headers for every reply.

This is primarily a JSON-only API; browsers should never receive a
meaningful response from it. The headers below are belt-and-braces
protection in case a misconfig ever exposes us:

* ``Strict-Transport-Security`` — tell any browser that does reach us
  to pin HTTPS for a year. Suppressed in dev/local/test so an HSTS pin
  can't trap a developer hitting ``http://localhost``.
* ``X-Content-Type-Options: nosniff`` — block MIME sniffing.
* ``X-Frame-Options: DENY`` — paired with CSP ``frame-ancestors``.
* ``Referrer-Policy`` — clamp cross-origin referer leakage.
* ``Permissions-Policy`` — deny browser feature use across the board.
* ``Content-Security-Policy: default-src 'none'; frame-ancestors 'none'``
  — strict default; relaxed for ``/admin``, ``/api/schema``, ``/api/docs``,
  ``/api/redoc`` so drf-spectacular / Django admin UI continue to load.

Toggle via ``SECURITY_HEADERS_ENABLED`` env var (default ``True``). The
middleware uses ``setdefault`` so any header already stamped by Django's
``SecurityMiddleware`` upstream wins — both can coexist safely.
"""

from __future__ import annotations

import os
from typing import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse

_DEV_ENVIRONMENTS = frozenset({"dev", "development", "test", "local"})

_BASE_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), interest-cohort=()"
    ),
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}

_HSTS_HEADER = ("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

# Admin + drf-spectacular UIs need to load CSS/JS/img bundles. The strict
# ``default-src 'none'`` would silently break them, so swap in a relaxed CSP
# scoped to those path prefixes only — every API/JSON route keeps the strict
# default above.
_DOCS_PATH_PREFIXES: tuple[str, ...] = (
    "/admin",
    "/api/schema",
    "/api/docs",
    "/api/redoc",
)
_DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src 'self' data: https://cdn.jsdelivr.net; "
    "font-src 'self' data: https://cdn.jsdelivr.net; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware:
    """Stamp a fixed defensive header set onto every outbound response."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response
        self.enabled = getattr(settings, "SECURITY_HEADERS_ENABLED", True)
        env = os.getenv("DJANGO_ENV", "").strip().lower()
        self.is_dev = env in _DEV_ENVIRONMENTS or getattr(settings, "DEBUG", False)

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if not self.enabled:
            return response
        if request.path.startswith(_DOCS_PATH_PREFIXES):
            response.headers["Content-Security-Policy"] = _DOCS_CSP
        for name, value in _BASE_HEADERS.items():
            response.headers.setdefault(name, value)
        if not self.is_dev:
            response.headers.setdefault(*_HSTS_HEADER)
        return response


__all__ = ["SecurityHeadersMiddleware"]
