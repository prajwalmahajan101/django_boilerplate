"""Base response class enforcing the standard envelope."""

from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.response import Response

from core.utils.logging import _request_id_var


class BaseResponse(Response):
    """Internal base that enforces the standard envelope.

    Every response body follows::

        {"success": bool, "message": str, "data": object | null, "errors": object | null, "request_id": str | null}
    """

    def __init__(
        self,
        *,
        success: bool,
        message: str,
        data: Any = None,
        errors: Any = None,
        request_id: str | None = None,
        status_code: int = status.HTTP_200_OK,
        **kwargs: Any,
    ) -> None:
        payload = {
            "success": success,
            "message": message,
            "data": data,
            "errors": errors,
            "request_id": request_id or _request_id_var.get(None),
        }
        super().__init__(data=payload, status=status_code, **kwargs)
