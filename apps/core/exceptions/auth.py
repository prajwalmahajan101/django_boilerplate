"""Auth + RBAC exception family.

These are service-layer / business-rule auth exceptions raised after the
authentication backend has run. DRF auth backends themselves should keep
raising ``rest_framework.exceptions.AuthenticationFailed`` so DRF's own
machinery (WWW-Authenticate header negotiation) stays intact.

Use this family for:

* Token decoding (``TokenExpiredError`` / ``TokenInvalidError`` /
  ``TokenRevokedError``).
* Service-layer guards that need to deny access (``PermissionDeniedError``)
  before reaching the route's ``HasResourcePermission`` check.
* Surfacing a soft-revoked API key from the audit path
  (``APIKeyRevokedError``) without leaking the distinction to the caller.

All map to HTTP 401 except ``PermissionDeniedError`` which is 403.
"""

from __future__ import annotations

from core.base.exception import BaseCustomError


class AuthenticationFailedError(BaseCustomError):
    """Credentials missing or invalid."""

    default_message = "Authentication failed."
    error_code = "AUTHENTICATION_FAILED"
    status_code = 401


class APIKeyRevokedError(AuthenticationFailedError):
    """The provided API key has been revoked.

    Returns 401 — same as ``AuthenticationFailedError`` — so a revoked
    key is indistinguishable from an unknown one from the caller's
    perspective. The distinction lives in the audit log only.
    """

    default_message = "API key has been revoked."
    error_code = "API_KEY_REVOKED"


class PermissionDeniedError(BaseCustomError):
    """Authenticated principal lacks the required permission."""

    default_message = "Permission denied."
    error_code = "PERMISSION_DENIED"
    status_code = 403


class TokenExpiredError(AuthenticationFailedError):
    """The supplied JWT signature is valid but ``exp`` has elapsed."""

    default_message = "Token has expired."
    error_code = "TOKEN_EXPIRED"


class TokenInvalidError(AuthenticationFailedError):
    """The supplied JWT failed signature / issuer / audience verification."""

    default_message = "Token is invalid."
    error_code = "TOKEN_INVALID"


class TokenRevokedError(AuthenticationFailedError):
    """The supplied JWT's ``jti`` is blacklisted (post-logout reuse)."""

    default_message = "Token has been revoked."
    error_code = "TOKEN_REVOKED"


__all__ = [
    "APIKeyRevokedError",
    "AuthenticationFailedError",
    "PermissionDeniedError",
    "TokenExpiredError",
    "TokenInvalidError",
    "TokenRevokedError",
]
