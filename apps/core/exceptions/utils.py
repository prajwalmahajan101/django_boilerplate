"""Generic helpers for normalizing outbound-call exceptions.

Two duck-typed helpers used by outbound HTTP clients and the audit layer
to record a consistent shape regardless of which exception family surfaced
the failure — the transport-layer :class:`APIError` (carrying
``status_code`` / ``response_body``), or any project-specific subclass that
wraps a 2xx-with-error envelope under ``response`` / ``response_status_code``.

No exception subclass needs to import this file — all access is via
:func:`getattr`, so adding a new attribute on a new exception class makes
it auto-discoverable.
"""

from __future__ import annotations

import json
from typing import Any

from rest_framework import status


def exception_response_payload(exc: BaseException) -> dict[str, Any] | None:
    """Return the upstream response body as a dict, regardless of exception type.

    Preference order:
      * ``response`` (dict) — wins immediately.
      * ``response_body`` (str) — parsed as JSON; falls back to ``details``
        on parse failure so the audit row still records something useful.
      * ``details`` (dict) — last-resort fallback.
    """
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        return response
    body = getattr(exc, "response_body", None)
    if isinstance(body, str) and body:
        try:
            parsed = json.loads(body)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    details = getattr(exc, "details", None)
    if isinstance(details, dict) and details:
        return details
    return None


def exception_wire_status(exc: BaseException) -> int:
    """Resolve the upstream wire status from any outbound-call exception.

    Preference order:
      1. ``response_status_code`` — set by project-specific errors that
         wrap a raw upstream HTTP status alongside a 2xx-shaped envelope.
      2. ``status_code`` — set by the transport-layer :class:`APIError`
         family on non-2xx responses.
      3. ``HTTP_502_BAD_GATEWAY`` — fallback so the audit row always
         carries a number.
    """
    return (
        getattr(exc, "response_status_code", None)
        or getattr(exc, "status_code", None)
        or status.HTTP_502_BAD_GATEWAY
    )


def normalize_outbound_exception(exc: BaseException) -> dict[str, Any]:
    """Bundle :func:`exception_response_payload` + :func:`exception_wire_status`.

    Convenience for audit-log writers and the ``@resilient`` wrapper:
    returns a single dict with ``status_code`` and ``response_body`` so the
    caller can hand the result straight to ``api_log.write(**normalized)``.
    """
    return {
        "status_code": exception_wire_status(exc),
        "response_body": exception_response_payload(exc),
    }


__all__ = [
    "exception_response_payload",
    "exception_wire_status",
    "normalize_outbound_exception",
]
