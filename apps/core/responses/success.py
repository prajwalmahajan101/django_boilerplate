"""Success response."""

from __future__ import annotations

from typing import Any

from rest_framework import status

from core.base.response import BaseResponse


class SuccessResponse[T](BaseResponse):
    """Return a successful result with typed *data*."""

    def __init__(
        self,
        *,
        data: T = None,
        message: str = "Success",
        status_code: int = status.HTTP_200_OK,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            success=True,
            message=message,
            data=data,
            status_code=status_code,
            **kwargs,
        )
