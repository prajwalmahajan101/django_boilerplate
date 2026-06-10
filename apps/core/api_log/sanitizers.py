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

import functools
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from core.utils.log_sanitization import sanitize_for_log
from django.conf import settings
from django.test.signals import setting_changed

UNSET: Any = object()

_DEFAULT_SENSITIVE = (
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
    "proxy-authorization",
)


@functools.lru_cache(maxsize=1)
def _sensitive_headers() -> frozenset[str]:
    raw = getattr(settings, "API_LOG_SENSITIVE_HEADERS", _DEFAULT_SENSITIVE) or ()
    return frozenset(h.lower() for h in raw)


def _bust_sensitive_headers_cache(sender, setting, **kwargs):
    if setting == "API_LOG_SENSITIVE_HEADERS":
        _sensitive_headers.cache_clear()


setting_changed.connect(_bust_sensitive_headers_cache)


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of ``headers`` with sensitive values replaced."""
    sensitive = _sensitive_headers()
    return {k: ("[REDACTED]" if k.lower() in sensitive else v) for k, v in headers.items()}


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


def summarise_body_for_audit(value: Any) -> Any:
    """Return a JSON-safe representation of a request/response body.

    Multipart payloads (Django ``QueryDict`` carrying uploaded files,
    raw multipart encoder objects) and raw ``bytes`` are not
    JSON-serialisable, so passing them through verbatim would let the
    api_log row drop silently when the persistence backend tries to
    encode the JSONB column. This helper renders such payloads as a
    structured summary (field names, filenames, content types, byte
    sizes) and falls back to :func:`audit_safe` for everything else.
    """
    if value is None:
        return None
    try:
        from django.core.files.uploadedfile import UploadedFile
        from django.http import QueryDict
    except Exception:
        QueryDict = None  # type: ignore[assignment]
        UploadedFile = None  # type: ignore[assignment]

    if QueryDict is not None and isinstance(value, QueryDict):
        fields: list[dict[str, Any]] = []
        for key in value.keys():
            for item in value.getlist(key):
                entry: dict[str, Any] = {"name": key}
                if UploadedFile is not None and isinstance(item, UploadedFile):
                    entry["filename"] = item.name
                    if item.content_type:
                        entry["content_type"] = item.content_type
                    entry["size_bytes"] = item.size
                elif isinstance(item, (bytes, bytearray)):
                    entry["size_bytes"] = len(item)
                elif isinstance(item, str):
                    entry["value"] = item if len(item) <= 200 else item[:200] + "…"
                else:
                    entry["value"] = str(item)
                fields.append(entry)
        scalar_view = {f["name"]: f.get("value") for f in fields if "value" in f}
        redacted_scalars = sanitize_for_log(scalar_view)
        for entry in fields:
            name = entry["name"]
            if "value" in entry and name in redacted_scalars:
                entry["value"] = redacted_scalars[name]
        return {"__multipart__": True, "fields": fields}

    if hasattr(value, "_fields") and value.__class__.__name__ in {
        "MultipartEncoder",
        "FormData",
    }:
        try:
            fields = []
            for field in value._fields:  # type: ignore[attr-defined]
                entry = {"name": getattr(field, "name", None) or str(field)}
                fields.append(entry)
            return {"__multipart__": True, "fields": fields}
        except Exception:
            pass

    return audit_safe(value)


def serialize_error_body(body: Any, max_len: int | None = None) -> str | None:
    """Best-effort string-encode an upstream error body.

    Falls back to ``str(body)`` if JSON-encoding fails so a malformed
    upstream response never masks the real failure under a secondary
    ``TypeError``. Output is truncated to honour the same body cap as
    :func:`serialize_body`.
    """
    if body is None:
        return None
    if max_len is None:
        max_len = int(getattr(settings, "API_LOG_MAX_BODY_LEN", 4096))
    if isinstance(body, str):
        return truncate(body, max_len)
    try:
        text = json.dumps(body, default=str)
    except Exception:
        text = str(body)
    return truncate(text, max_len)


def serialize_body(value: Any, max_len: int | None = None) -> str | None:
    """Render ``value`` as a string body of at most ``max_len`` chars.

    Sensitive fields (``password``, ``token``, ``api_key`` …) are
    redacted via :func:`sanitize_for_log` before the payload is
    JSON-encoded — the rendered string lands in the persistent
    ``api_logs`` table, so plaintext credentials must never reach it.
    Strings/bytes that look like JSON are parsed and recursively
    redacted; non-JSON strings fall back to scalar sanitisation
    (control-char escaping, length cap).
    """
    if value is None or value is UNSET:
        return None
    if max_len is None:
        max_len = int(getattr(settings, "API_LOG_MAX_BODY_LEN", 4096))
    try:
        structured: Any
        if isinstance(value, (bytes, bytearray)):
            decoded = bytes(value).decode("utf-8", errors="replace")
            structured = _try_parse_json(decoded, fallback=decoded)
        elif isinstance(value, str):
            structured = _try_parse_json(value, fallback=value)
        else:
            structured = value

        redacted = sanitize_for_log(structured, max_string_length=max_len)
        if isinstance(redacted, str):
            text = redacted
        else:
            text = json.dumps(redacted, default=str)
        return truncate(text, max_len)
    except Exception:
        return None


def _try_parse_json(text: str, fallback: Any) -> Any:
    """Return ``json.loads(text)`` only when it yields a dict or list."""
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return fallback
    if isinstance(parsed, (dict, list)):
        return parsed
    return fallback


def compute_ttl() -> int | None:
    """Return a unix-epoch expiry derived from ``API_LOG_TTL_DAYS``."""
    days = int(getattr(settings, "API_LOG_TTL_DAYS", 0) or 0)
    if days <= 0:
        return None
    return int((datetime.now(UTC) + timedelta(days=days)).timestamp())


__all__ = [
    "UNSET",
    "audit_safe",
    "compute_ttl",
    "redact_headers",
    "serialize_body",
    "serialize_error_body",
    "summarise_body_for_audit",
    "truncate",
]
