"""Concrete :class:`core.auth.AuthProvider` implementations for accounts.

Each provider is a thin adapter over an existing DRF authentication
class so the registry can name, order, and introspect them without
duplicating their authentication logic.
"""

from __future__ import annotations

from typing import Any

from accounts.authentication import APIKeyAuthentication


class APIKeyProvider:
    name = "api_key"

    def __init__(self) -> None:
        self._auth = APIKeyAuthentication()

    def authenticate(self, request: Any):
        return self._auth.authenticate(request)

    def authenticate_header(self, request: Any) -> str:
        return "X-API-Key"


class JWTProvider:
    name = "jwt"

    def __init__(self) -> None:
        from rest_framework_simplejwt.authentication import JWTAuthentication

        self._auth = JWTAuthentication()

    def authenticate(self, request: Any):
        return self._auth.authenticate(request)

    def authenticate_header(self, request: Any) -> str:
        return self._auth.authenticate_header(request)


class GoogleOAuthProvider:
    """Routed (not per-request) — the Google login view mints a JWT
    that :class:`JWTProvider` then validates. Always returns ``None``."""

    name = "oauth_google"

    def authenticate(self, request: Any):
        return None


__all__ = ["APIKeyProvider", "GoogleOAuthProvider", "JWTProvider"]
