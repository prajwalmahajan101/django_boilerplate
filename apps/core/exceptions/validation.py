"""``ValidationError`` — semantic / business-rule validation failures.

Distinct from DRF's ``rest_framework.serializers.ValidationError`` (request
payload schema mismatch). Use this for business-rule rejections that pass
the serializer but violate domain invariants — e.g. "balance cannot go
below zero", "this transition is illegal in the current state".

Surfaces the offending ``field`` in ``errors[].field`` so the central DRF
handler doesn't need a special case.
"""

from __future__ import annotations

from typing import Any

from core.base.exception import BaseCustomError


class ValidationError(BaseCustomError):
    """Semantic / business-rule validation failed."""

    default_message = "Validation failed."
    error_code = "VALIDATION_ERROR"
    status_code = 400

    def __init__(
        self,
        message: str | None = None,
        *,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.field = field
        self.details = details or {}

    def get_details(self) -> dict[str, Any] | None:
        return self.details or None

    def to_error_dict(self) -> dict[str, Any]:
        return {
            "code": self.get_error_code(),
            "message": self.message,
            "field": self.field,
            "details": self.get_details(),
        }


__all__ = ["ValidationError"]
