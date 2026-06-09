"""Paginated response."""

from __future__ import annotations

import math
from typing import Any

from core.base.response import BaseResponse
from django.core.paginator import Page
from rest_framework import status


class PaginatedResponse[T](BaseResponse):
    """Return a paginated list.

    Accepts a Django ``Page`` object *or* raw values::

        # From a Django Paginator
        return PaginatedResponse(page=page_obj, items=serializer.data)

        # Manual
        return PaginatedResponse(
            items=items, total_count=100, page_size=20, page_number=1,
        )
    """

    def __init__(
        self,
        *,
        page: Page | None = None,
        items: list[T] | None = None,
        total_count: int | None = None,
        page_size: int | None = None,
        page_number: int | None = None,
        message: str = "Success",
        status_code: int = status.HTTP_200_OK,
        **kwargs: Any,
    ) -> None:
        if page is not None:
            items = items if items is not None else list(page.object_list)
            total_count = page.paginator.count
            page_size = page.paginator.per_page
            page_number = page.number
            total_pages = page.paginator.num_pages
            has_previous = page.has_previous()
            has_next = page.has_next()
        else:
            if items is None:
                items = []
            if total_count is None or page_size is None or page_number is None:
                raise ValueError(
                    "When 'page' is not provided, 'total_count', 'page_size', "
                    "and 'page_number' are required."
                )
            total_pages = math.ceil(total_count / page_size) if page_size > 0 else 0
            has_previous = page_number > 1
            has_next = page_number < total_pages

        data = {
            "items": items,
            "pagination": {
                "total_count": total_count,
                "page_size": page_size,
                "page_number": page_number,
                "total_pages": total_pages,
                "has_previous": has_previous,
                "has_next": has_next,
            },
        }

        super().__init__(
            success=True,
            message=message,
            data=data,
            status_code=status_code,
            **kwargs,
        )
