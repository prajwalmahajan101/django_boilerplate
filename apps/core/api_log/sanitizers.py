"""Pure sanitizers for ``api_logs`` payloads.

Header redaction, body truncation, JSON-safety for the ``extra``
column, and TTL computation — all stateless and synchronous so they
can be unit-tested without any of the decorator machinery.

Settings honoured:

* ``API_LOG_SENSITIVE_HEADERS`` — list of header names whose values
  are replaced with ``[REDACTED]`` (case-insensitive match).
* ``API_LOG_MAX_BODY_LEN`` — character cap applied by
  :func:`serialize_body`.
* ``API_LOG_TTL_DAYS`` — days-from-now expiry stamped on every row.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from django.conf import settings

UNSET: Any = object()

_DEFAULT_SENSITIVE = (
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
    "proxy-authorization",
)


def _sensitive_headers() -> set[str]:
    raw = getattr(settings, "API_LOG_SENSITIVE_HEADERS", _DEFAULT_SENSITIVE) or ()
    return {h.lower() for h in raw}


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of ``headers`` with sensitive values replaced."""
    sensitive = _sensitive_headers()
    return {
        k: ("[REDACTED]" if k.lower() in sensitive else v) for k, v in headers.items()
    }


def truncate(text: str | None, max_len: int) -> str | None:
    """Cap ``text`` at ``max_len`` characters with an ellipsis marker."""
    if text is None:
        return None
    return text if len(text) <= max_len else text[:max_len] + "…[truncated]"


def audit_safe(value: Any) -> Any:
    """Render ``value`` in a JSON-safe shape for the ``extra`` column.

    Raw bytes (e.g. ``file_bytes`` from a multipart upload) cannot
    land in JSON — passing them through would raise inside the
    persistence backend, which the fire-and-forget queue would
    swallow, silently dropping the row. Convert bytes to a size
    summary; everything else passes through.
    """
    if isinstance(value, (bytes, bytearray)):
        return {"__bytes__": True, "size_bytes": len(value)}
    return value


def serialize_body(value: Any, max_len: int | None = None) -> str | None:
    """Render ``value`` as a string body of at most ``max_len`` chars.

    Strings pass through; bytes are UTF-8-decoded with errors replaced;
    everything else is JSON-dumped with ``default=str`` so the call
    never raises on unexpected payload shapes.
    """
    if value is None or value is UNSET:
        return None
    if max_len is None:
        max_len = int(getattr(settings, "API_LOG_MAX_BODY_LEN", 4096))
    try:
        if isinstance(value, str):
            text = value
        elif isinstance(value, (bytes, bytearray)):
            text = bytes(value).decode("utf-8", errors="replace")
        else:
            text = json.dumps(value, default=str)
        return truncate(text, max_len)
    except Exception:
        return None


def compute_ttl() -> int | None:
    """Return a unix-epoch expiry derived from ``API_LOG_TTL_DAYS``."""
    days = int(getattr(settings, "API_LOG_TTL_DAYS", 0) or 0)
    if days <= 0:
        return None
    return int((datetime.now(timezone.utc) + timedelta(days=days)).timestamp())


__all__ = [
    "UNSET",
    "audit_safe",
    "compute_ttl",
    "redact_headers",
    "serialize_body",
    "truncate",
]
