"""Data manipulation utilities."""

from __future__ import annotations

from typing import Any

from core.exceptions.repository import InvalidInputError


def filter_dict_keys(
    data: list[dict[str, Any]], keys: list[str], strict: bool = False
) -> list[dict[str, Any]]:
    """Filter dictionaries to only include specified keys."""
    if not keys:
        return data

    if strict:
        return [{k: row[k] for k in keys} for row in data]
    else:
        return [{k: row.get(k) for k in keys if k in row} for row in data]


def sanitize_string(value: str, max_length: int = 1000) -> str:
    """Sanitize string value by enforcing length limits.

    Does NOT perform character escaping because parameter values are passed
    to database drivers via parameterized queries which handle escaping internally.
    """
    if len(value) > max_length:
        raise InvalidInputError(
            f"String too long: {len(value)} chars (max: {max_length})"
        )

    return value


def parse_bool(value: Any) -> bool:
    """Parse various types to boolean."""
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "1", "yes", "on")
