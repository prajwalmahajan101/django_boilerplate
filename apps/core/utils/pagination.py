"""DRF pagination class that produces the standard envelope format."""

from __future__ import annotations

from typing import Any

from rest_framework.pagination import PageNumberPagination

from core.responses.paginated import PaginatedResponse


class StandardPageNumberPagination(PageNumberPagination):
    """Page-number pagination emitting the standard envelope.

    Query params: ``page`` (1-based) and ``page_size``.
    Delegates to ``PaginatedResponse`` for envelope consistency.
    """

    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data: list[Any]) -> PaginatedResponse:
        return PaginatedResponse(page=self.page, items=data)
