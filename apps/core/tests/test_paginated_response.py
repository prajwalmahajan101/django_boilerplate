"""Tests for ``core.responses.paginated.PaginatedResponse``.

Stays at the unit tier — exercises both the Django ``Page`` branch and
the manual-construction branch with raw values, plus the edge cases
(empty page, last page, page-size-zero guard, missing-required-arg
validation).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from core.responses.paginated import PaginatedResponse
from rest_framework import status


def _page(*, items, total, per_page, number, num_pages, has_prev, has_next):
    """Mock Django ``Page`` matching the attributes PaginatedResponse reads."""
    page = MagicMock()
    page.object_list = items
    page.paginator.count = total
    page.paginator.per_page = per_page
    page.paginator.num_pages = num_pages
    page.number = number
    page.has_previous.return_value = has_prev
    page.has_next.return_value = has_next
    return page


def _data(response):
    """Pull the ``data`` payload out of a DRF Response wrapper."""
    return response.data["data"]


def test_from_django_page_middle_page():
    page = _page(
        items=[{"id": 1}, {"id": 2}],
        total=10,
        per_page=2,
        number=3,
        num_pages=5,
        has_prev=True,
        has_next=True,
    )
    resp = PaginatedResponse(page=page)
    body = _data(resp)
    assert body["items"] == [{"id": 1}, {"id": 2}]
    assert body["pagination"] == {
        "total_count": 10,
        "page_size": 2,
        "page_number": 3,
        "total_pages": 5,
        "has_previous": True,
        "has_next": True,
    }


def test_from_django_page_overrides_items_when_provided():
    page = _page(
        items=[{"id": "raw"}],
        total=1,
        per_page=10,
        number=1,
        num_pages=1,
        has_prev=False,
        has_next=False,
    )
    resp = PaginatedResponse(page=page, items=[{"id": "serialized"}])
    assert _data(resp)["items"] == [{"id": "serialized"}]


def test_manual_construction_middle_page():
    resp = PaginatedResponse(items=[1, 2, 3], total_count=12, page_size=3, page_number=2)
    body = _data(resp)
    assert body["items"] == [1, 2, 3]
    assert body["pagination"] == {
        "total_count": 12,
        "page_size": 3,
        "page_number": 2,
        "total_pages": 4,
        "has_previous": True,
        "has_next": True,
    }


def test_manual_construction_empty_page():
    resp = PaginatedResponse(items=[], total_count=0, page_size=10, page_number=1)
    body = _data(resp)
    assert body["items"] == []
    assert body["pagination"]["total_pages"] == 0
    assert body["pagination"]["has_previous"] is False
    assert body["pagination"]["has_next"] is False


def test_manual_construction_last_page():
    resp = PaginatedResponse(items=[42], total_count=21, page_size=10, page_number=3)
    pag = _data(resp)["pagination"]
    assert pag["total_pages"] == 3
    assert pag["has_previous"] is True
    assert pag["has_next"] is False


def test_manual_construction_first_page():
    resp = PaginatedResponse(items=[1], total_count=21, page_size=10, page_number=1)
    pag = _data(resp)["pagination"]
    assert pag["has_previous"] is False
    assert pag["has_next"] is True


def test_manual_construction_defaults_items_when_omitted():
    resp = PaginatedResponse(total_count=0, page_size=10, page_number=1)
    assert _data(resp)["items"] == []


def test_manual_construction_requires_pagination_args():
    with pytest.raises(ValueError, match="When 'page' is not provided"):
        PaginatedResponse(items=[1, 2, 3], page_size=10, page_number=1)
    with pytest.raises(ValueError, match="When 'page' is not provided"):
        PaginatedResponse(items=[1, 2, 3], total_count=10, page_number=1)
    with pytest.raises(ValueError, match="When 'page' is not provided"):
        PaginatedResponse(items=[1, 2, 3], total_count=10, page_size=10)


def test_page_size_zero_guards_against_divzero():
    resp = PaginatedResponse(items=[], total_count=0, page_size=0, page_number=1)
    assert _data(resp)["pagination"]["total_pages"] == 0


def test_status_code_and_message_defaults():
    resp = PaginatedResponse(items=[], total_count=0, page_size=10, page_number=1)
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["message"] == "Success"


def test_custom_status_and_message_passthrough():
    resp = PaginatedResponse(
        items=[],
        total_count=0,
        page_size=10,
        page_number=1,
        message="Filtered",
        status_code=status.HTTP_206_PARTIAL_CONTENT,
    )
    assert resp.status_code == status.HTTP_206_PARTIAL_CONTENT
    assert resp.data["message"] == "Filtered"
