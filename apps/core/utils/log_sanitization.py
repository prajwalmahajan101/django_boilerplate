"""Logging sanitization utilities.

Provides functions for sanitizing values before logging to prevent:
- Log injection attacks (newlines, control characters)
- Sensitive data exposure (passwords, tokens, etc.)
- Memory issues from logging large data structures
"""

import re
from typing import Any

from django.conf import settings

# =============================================================================
# Logging Sanitization Utilities
# =============================================================================

# Fallback defaults if LOG_SANITIZATION is missing or incomplete.
_DEFAULTS = {
    "SANITIZE_ENABLED": True,
    "MAX_STRING_LENGTH": 200,
    "MAX_DICT_KEYS": 20,
    "MAX_LIST_ITEMS": 10,
    "SENSITIVE_PATTERN": re.compile(
        r"password|secret|token|key|auth|credential|api_key|bearer|jwt",
        re.IGNORECASE,
    ),
    "MASK_VALUE": "***REDACTED***",
    "EXCLUDED_FIELDS": frozenset(),
}


def _get_sanitization_config() -> dict:
    """Get LOG_SANITIZATION from settings with safe defaults."""
    config = getattr(settings, "LOG_SANITIZATION", {})
    return {key: config.get(key, default) for key, default in _DEFAULTS.items()}


def sanitize_for_log(
    value: Any,
    max_string_length: int | None = None,
    max_dict_keys: int | None = None,
    max_list_items: int | None = None,
) -> Any:
    r"""Sanitize a value for safe logging.

    This function sanitizes values to prevent:
    - Log injection attacks (newlines, control characters)
    - Sensitive data exposure (passwords, tokens, etc.)
    - Memory issues from logging large data structures
    """
    config = _get_sanitization_config()

    if not config["SANITIZE_ENABLED"]:
        return value

    max_str = max_string_length or config["MAX_STRING_LENGTH"]
    max_keys = max_dict_keys or config["MAX_DICT_KEYS"]
    max_items = max_list_items or config["MAX_LIST_ITEMS"]

    return _sanitize_value(value, max_str, max_keys, max_items, depth=0)


def _sanitize_value(
    value: Any,
    max_str: int,
    max_keys: int,
    max_items: int,
    depth: int,
) -> Any:
    """Internal recursive sanitization function."""
    max_depth = 5
    if depth > max_depth:
        return "<max depth exceeded>"

    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, int | float):
        return value

    if isinstance(value, str):
        return _sanitize_string_for_log(value, max_str)

    if isinstance(value, bytes):
        return f"<bytes: {len(value)} bytes>"

    if isinstance(value, dict):
        return _sanitize_dict_for_log(value, max_str, max_keys, max_items, depth)

    if isinstance(value, list | tuple | set | frozenset):
        return _sanitize_iterable_for_log(value, max_str, max_keys, max_items, depth)

    try:
        str_value = str(value)
        return _sanitize_string_for_log(str_value, max_str)
    except Exception:
        return f"<{type(value).__name__}: unserializable>"


def _sanitize_string_for_log(value: str, max_length: int) -> str:
    """Sanitize a string value for logging."""
    sanitized = value.replace("\\", "\\\\")
    sanitized = sanitized.replace("\n", "\\n")
    sanitized = sanitized.replace("\r", "\\r")
    sanitized = sanitized.replace("\t", "\\t")

    sanitized = "".join(char if ord(char) >= 32 else f"\\x{ord(char):02x}" for char in sanitized)

    if len(sanitized) > max_length:
        half = (max_length - 20) // 2
        sanitized = f"{sanitized[:half]}...{sanitized[-half:]} ({len(value)} chars)"

    return sanitized


def _sanitize_dict_for_log(
    value: dict[str, Any],
    max_str: int,
    max_keys: int,
    max_items: int,
    depth: int,
) -> dict[str, Any]:
    """Sanitize a dictionary for logging."""
    result = {}
    config = _get_sanitization_config()
    sensitive_pattern = config["SENSITIVE_PATTERN"]
    excluded_fields = config["EXCLUDED_FIELDS"]
    mask_value = config["MASK_VALUE"]

    keys = list(value.keys())
    truncated = len(keys) > max_keys

    for i, key in enumerate(keys):
        if i >= max_keys:
            break

        str_key = str(key)
        lower_key = str_key.lower()

        if lower_key in excluded_fields:
            continue

        if sensitive_pattern.search(str_key):
            result[str_key] = mask_value
        else:
            result[str_key] = _sanitize_value(value[key], max_str, max_keys, max_items, depth + 1)

    if truncated:
        result["__truncated__"] = f"{len(keys) - max_keys} more keys"

    return result


def _sanitize_iterable_for_log(
    value: list | tuple | set | frozenset,
    max_str: int,
    max_keys: int,
    max_items: int,
    depth: int,
) -> list:
    """Sanitize an iterable for logging."""
    items = list(value)
    truncated = len(items) > max_items

    result = [
        _sanitize_value(item, max_str, max_keys, max_items, depth + 1) for item in items[:max_items]
    ]

    if truncated:
        result.append(f"...and {len(items) - max_items} more items")

    return result


def safe_log_dict(**kwargs: Any) -> dict[str, Any]:
    """Create a sanitized dictionary for logging extra fields."""
    return sanitize_for_log(kwargs)


def truncate_for_log(value: str, max_length: int = 100) -> str:
    """Truncate a string for logging with ellipsis."""
    if not isinstance(value, str):
        value = str(value)

    if len(value) <= max_length:
        return value

    half = (max_length - 10) // 2
    return f"{value[:half]}...{value[-half:]} ({len(value)} chars)"
