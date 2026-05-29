"""Auth provider contract — shared by every concrete provider.

Every provider exposes:

* ``name`` — short identifier matching an entry in
  ``settings.AUTH_ENABLED_PROVIDERS``;
* ``authenticate(request)`` — DRF-compatible signature returning
  ``(user, auth)`` on success, ``None`` when this provider sees no
  credentials of its kind, or raising
  ``rest_framework.exceptions.AuthenticationFailed`` when credentials
  are present but invalid.

Returning ``None`` (rather than raising) lets the registry fall
through to the next provider. This is the same contract DRF's
``BaseAuthentication.authenticate`` already uses.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AuthProvider(Protocol):
    """Authenticate inbound requests."""

    name: str

    def authenticate(self, request: Any) -> tuple[Any, Any] | None:
        """Resolve ``request`` to a ``(user, auth)`` tuple or ``None``."""
        ...


__all__ = ["AuthProvider"]
