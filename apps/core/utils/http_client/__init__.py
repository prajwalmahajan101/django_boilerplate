"""Outbound HTTP client package — split for extensibility.

Public surface (re-exported here for backwards-compatible imports):

* :func:`make_http_request` — single entry point.
* :class:`HttpResponse` — dataclass returned on success.
* :class:`AuthType`, :func:`build_headers` — auth helpers for non-Basic
  flows; ``requests`` handles Basic via the ``auth=`` tuple.
* :class:`ExternalTimeoutError`, :class:`TransientError`,
  :class:`InvalidOutboundURLError` — typed exceptions the client raises.

Private SSRF / DNS-pin internals (``_resolve_and_validate``,
``_assert_url_allowlisted``, ``_pinned_dns``, ``_orig_getaddrinfo``)
are re-exported too so the existing allow-list / pin tests keep
working without reaching into a private submodule.

For the layout rationale (one module per concern: session, auth,
errors, client) see the source file
``apps/core/utils/http_client/_client.py``.
"""

from core.utils.http_client._auth import AuthType, build_headers
from core.utils.http_client._client import (
    _assert_public_url,
    _assert_url_allowlisted,
    _orig_getaddrinfo,
    _patched_getaddrinfo,
    _pin_dns,
    _pinned_dns,
    _resolve_and_validate,
    make_http_request,
)
from core.utils.http_client._errors import (
    ExternalTimeoutError,
    HttpResponse,
    InvalidOutboundURLError,
    TransientError,
)
from core.utils.http_client._session import get_session

__all__ = [
    "AuthType",
    "ExternalTimeoutError",
    "HttpResponse",
    "InvalidOutboundURLError",
    "TransientError",
    "_assert_public_url",
    "_assert_url_allowlisted",
    "_orig_getaddrinfo",
    "_patched_getaddrinfo",
    "_pin_dns",
    "_pinned_dns",
    "_resolve_and_validate",
    "build_headers",
    "get_session",
    "make_http_request",
]
