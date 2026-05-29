"""Error-message composition for ``ApiLog.error`` payloads.

Single concern: turn an exception into the pipe-delimited summary
string the audit row persists. Lives in its own module so callers
(and tests) don't have to reach into the decorator hot path or
import the typed exception hierarchy at module load.
"""

from __future__ import annotations


def build_error_message(exc: BaseException) -> str:
    """Compose a single-line error string from ``exc``.

    For ``BaseCustomError`` subclasses, folds in ``status_code`` and the
    structured ``get_details()`` payload so the audit row carries the
    full upstream context.

    Returns:
        Pipe-delimited summary string, e.g.
        ``"Service unavailable | status_code=503 | details={'service_name': 's3'}"``.
    """
    from core.base.exception import BaseCustomError

    parts: list[str] = [f"{type(exc).__name__}: {exc}"]
    if isinstance(exc, BaseCustomError):
        status_code = getattr(exc, "status_code", None)
        if status_code is not None:
            parts.append(f"status_code={status_code}")
        try:
            details = exc.get_details()
        except Exception:
            details = None
        if details:
            parts.append(f"details={details}")
        response_body = getattr(exc, "response_body", None)
        if response_body:
            parts.append(f"response_body={response_body}")
    return " | ".join(parts)


__all__ = ["build_error_message"]
