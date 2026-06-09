"""Auth-header builders for outbound HTTP calls.

Mirrors the layout of ``fastapi_boilerplate/src/core/utils/http_client/_auth.py``
so the two clients stay shape-compatible. The Django call site today
only uses HTTP Basic via the ``auth`` tuple passed to
``requests.Session.request``; the bearer / API-key helpers are here so
future call sites have an idiomatic extension point instead of growing
ad-hoc header dicts at every service.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping


class AuthType(enum.Enum):
    """How outbound credentials are attached to a request."""

    NONE = "none"
    BASIC = "basic"
    BEARER = "bearer"
    API_KEY = "api_key"


def build_headers(
    *,
    auth_type: AuthType = AuthType.NONE,
    token: str | None = None,
    api_key_header: str = "X-API-Key",
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Assemble the request headers for the given auth shape.

    ``BASIC`` is not handled here — pass the ``(user, password)`` tuple
    to ``make_http_request(auth=...)`` instead; ``requests`` builds the
    ``Authorization`` header itself.
    """
    headers: dict[str, str] = dict(extra or {})
    if auth_type is AuthType.BEARER:
        if not token:
            raise ValueError("BEARER auth requires a token.")
        headers["Authorization"] = f"Bearer {token}"
    elif auth_type is AuthType.API_KEY:
        if not token:
            raise ValueError("API_KEY auth requires a token.")
        headers[api_key_header] = token
    return headers


__all__ = ["AuthType", "build_headers"]
