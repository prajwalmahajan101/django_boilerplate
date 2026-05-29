"""Shared response shapes used across the accounts api_schemas sub-modules.

These private schema fragments are consumed by auth/user/api_key endpoints
to keep error / throttle / auth-required envelope shapes consistent. Mirrors
the ``apps/partners/api_schemas/_common.py`` precedent.
"""

from __future__ import annotations

_error_response_schema = {
    "type": "object",
    "properties": {
        "success": {"type": "boolean", "example": False},
        "message": {"type": "string"},
    },
    "required": ["success", "message"],
}

_validation_error_schema = {
    "type": "object",
    "description": "DRF validation error — keys are field names, values are lists of error strings.",
    "additionalProperties": {
        "type": "array",
        "items": {"type": "string"},
    },
    "example": {
        "code": ["This field is required."],
        "redirect_uri": ["Enter a valid URL."],
    },
}

_jwt_token_pair_schema = {
    "type": "object",
    "properties": {
        "access": {"type": "string", "example": "eyJhbGciOiJIUzI1NiIs..."},
        "refresh": {"type": "string", "example": "eyJhbGciOiJIUzI1NiIs..."},
    },
    "required": ["access", "refresh"],
}

_throttled_response_schema = {
    "type": "object",
    "properties": {
        "detail": {
            "type": "string",
            "example": "Request was throttled. Expected available in 3600 seconds.",
        },
    },
    "required": ["detail"],
}

_auth_required_schema = {
    "type": "object",
    "properties": {
        "detail": {
            "type": "string",
            "example": "Authentication credentials were not provided.",
        },
    },
    "required": ["detail"],
}
