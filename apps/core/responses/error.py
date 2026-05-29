"""Error response."""

from __future__ import annotations

from typing import Any

from rest_framework import status

from core.base.response import BaseResponse


class ErrorResponse(BaseResponse):
    """Return an error with structured error details."""

    def __init__(
        self,
        *,
        message: str = "An error occurred",
        errors: list[dict[str, Any]] | None = None,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            success=False,
            message=message,
            errors=errors,
            status_code=status_code,
            **kwargs,
        )
