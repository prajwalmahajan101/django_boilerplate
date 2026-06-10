"""``CompositeAuthentication`` — single DRF auth class that delegates to the registry.

This is the only entry in
``REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]`` after the
registry port. It iterates :func:`enabled_providers` and returns the
first non-``None`` ``(user, auth)`` result, matching DRF's existing
per-class fall-through semantics.
"""

from __future__ import annotations

import contextlib

from core.auth.registry import enabled_providers
from rest_framework.authentication import BaseAuthentication


class CompositeAuthentication(BaseAuthentication):
    """DRF auth class delegating to the registered provider chain."""

    def authenticate(self, request):
        providers = self._providers_for(request)
        for provider in providers:
            result = provider.authenticate(request)
            if result is not None:
                return result
        return None

    def authenticate_header(self, request):
        # Surface the first provider's WWW-Authenticate hint if any.
        for provider in self._providers_for(request):
            header = getattr(provider, "authenticate_header", None)
            if callable(header):
                value = header(request)
                if value:
                    return value
        return None

    @staticmethod
    def _providers_for(request):
        """Snapshot the provider chain once per request.

        DRF calls ``authenticate`` first and (on failure) reaches into
        ``authenticate_header`` separately. Caching the registry walk
        on the request avoids a second registry-lock acquisition + list
        construction on every 401.

        ``isinstance(cached, list)`` (rather than ``is None``) is the
        cache-hit gate so test doubles like ``MagicMock`` — whose
        attribute access auto-creates a mock instead of raising — do
        not poison the cache slot and silently disable the provider
        chain.
        """
        cached = getattr(request, "_composite_auth_providers", None)
        if not isinstance(cached, list):
            cached = enabled_providers()
            with contextlib.suppress(AttributeError):
                request._composite_auth_providers = cached
        return cached
