"""``CompositeAuthentication`` — single DRF auth class that delegates to the registry.

This is the only entry in
``REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]`` after the
registry port. It iterates :func:`enabled_providers` and returns the
first non-``None`` ``(user, auth)`` result, matching DRF's existing
per-class fall-through semantics.
"""

from __future__ import annotations

from rest_framework.authentication import BaseAuthentication

from core.auth.registry import enabled_providers


class CompositeAuthentication(BaseAuthentication):
    """DRF auth class delegating to the registered provider chain."""

    def authenticate(self, request):
        for provider in enabled_providers():
            result = provider.authenticate(request)
            if result is not None:
                return result
        return None

    def authenticate_header(self, request):
        # Surface the first provider's WWW-Authenticate hint if any.
        for provider in enabled_providers():
            header = getattr(provider, "authenticate_header", None)
            if callable(header):
                value = header(request)
                if value:
                    return value
        return None
