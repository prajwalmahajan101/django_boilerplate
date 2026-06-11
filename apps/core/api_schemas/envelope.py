"""Envelope schema builders + example builders + shared pagination params.

The envelope is the only response shape this project emits; every
schema below conforms to it. See ``__init__.py`` for the contract.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import OpenApiParameter

# ---------------------------------------------------------------------------
# Shared pagination parameters for list endpoints
# ---------------------------------------------------------------------------

PAGINATION_PARAMETERS = [
    OpenApiParameter(
        name="page",
        type=int,
        location=OpenApiParameter.QUERY,
        required=False,
        description="Page number (1-based). Defaults to 1.",
    ),
    OpenApiParameter(
        name="page_size",
        type=int,
        location=OpenApiParameter.QUERY,
        required=False,
        description="Number of items per page (1–100). Defaults to 20.",
    ),
]


# ---------------------------------------------------------------------------
# Envelope schema builders
# ---------------------------------------------------------------------------


def envelope_schema(
    data_schema: dict[str, Any] | None = None,
    *,
    success: bool = True,
    message_example: str = "Success",
) -> dict[str, Any]:
    """Wrap *data_schema* in the standard response envelope."""
    return {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "example": success},
            "message": {"type": "string", "example": message_example},
            "data": data_schema or {"type": "object", "nullable": True},
            "errors": {
                "type": "array",
                "items": {"type": "object"},
                "nullable": True,
                "example": None,
            },
            "request_id": {
                "type": "string",
                "nullable": True,
                "example": "b0f1e6c2-1a1e-4f7a-9a6a-0b0e2d2b2a9e",
            },
        },
        "required": ["success", "message"],
    }


def paginated_envelope_schema(item_schema: dict[str, Any]) -> dict[str, Any]:
    """Envelope with a paginated list payload in ``data``."""
    return envelope_schema(
        {
            "type": "object",
            "properties": {
                "items": {"type": "array", "items": item_schema},
                "pagination": {
                    "type": "object",
                    "properties": {
                        "total_count": {"type": "integer", "example": 42},
                        "page_size": {"type": "integer", "example": 20},
                        "page_number": {"type": "integer", "example": 1},
                        "total_pages": {"type": "integer", "example": 3},
                        "has_previous": {"type": "boolean", "example": False},
                        "has_next": {"type": "boolean", "example": True},
                    },
                    "required": [
                        "total_count",
                        "page_size",
                        "page_number",
                        "total_pages",
                        "has_previous",
                        "has_next",
                    ],
                },
            },
            "required": ["items", "pagination"],
        }
    )


def error_envelope(
    *, message_example: str, errors_example: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Error envelope with populated ``errors`` example."""
    return {
        "type": "object",
        "properties": {
            "success": {"type": "boolean", "example": False},
            "message": {"type": "string", "example": message_example},
            "data": {"type": "object", "nullable": True, "example": None},
            "errors": {
                "type": "array",
                "items": {"type": "object"},
                "nullable": True,
                "example": errors_example,
            },
            "request_id": {
                "type": "string",
                "nullable": True,
                "example": "b0f1e6c2-1a1e-4f7a-9a6a-0b0e2d2b2a9e",
            },
        },
        "required": ["success", "message"],
    }


# ---------------------------------------------------------------------------
# Example builders (concrete JSON payloads used by OpenApiExample)
# ---------------------------------------------------------------------------


def envelope_example(data: Any, message: str = "Success") -> dict[str, Any]:
    """Return a sample success envelope for OpenAPI schema examples."""
    return {
        "success": True,
        "message": message,
        "data": data,
        "errors": None,
        "request_id": "b0f1e6c2-1a1e-4f7a-9a6a-0b0e2d2b2a9e",
    }


def error_example(message: str, errors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return a sample error envelope for OpenAPI schema examples."""
    return {
        "success": False,
        "message": message,
        "data": None,
        "errors": errors,
        "request_id": "b0f1e6c2-1a1e-4f7a-9a6a-0b0e2d2b2a9e",
    }
