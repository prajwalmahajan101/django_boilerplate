"""``SelectiveCORSMiddleware`` — CORS that skips configured path prefixes.

Some endpoints (server-to-server webhooks, internal callbacks) must
appear *invisible* to browser CORS preflights, while the public API
needs permissive CORS. ``django-cors-headers``'s
:class:`corsheaders.middleware.CorsMiddleware` is all-or-nothing per
regex; this middleware wraps it and short-circuits when the request
path begins with any ``CORS_EXCLUDED_PREFIXES`` entry — letting the
request flow through with no CORS headers attached at all.

Use as a drop-in replacement for ``corsheaders.middleware.CorsMiddleware``
in ``MIDDLEWARE``. Configure prefixes via the
``CORS_EXCLUDED_PREFIXES`` env var (comma-separated, e.g.
``/webhooks/,/api/internal/``).
"""

from __future__ import annotations

from collections.abc import Callable

from corsheaders.middleware import CorsMiddleware
from django.conf import settings
from django.http import HttpRequest, HttpResponse


class SelectiveCORSMiddleware:
    """Delegate to ``CorsMiddleware`` unless the request path is excluded."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self.excluded_prefixes: tuple[str, ...] = tuple(
            getattr(settings, "CORS_EXCLUDED_PREFIXES", ())
        )
        # Wrap the underlying CorsMiddleware exactly once so its setup
        # (regex compile, header parsing) runs at startup, not per-request.
        self._cors = CorsMiddleware(get_response)

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if self.excluded_prefixes and request.path.startswith(self.excluded_prefixes):
            return self.get_response(request)
        return self._cors(request)


__all__ = ["SelectiveCORSMiddleware"]
