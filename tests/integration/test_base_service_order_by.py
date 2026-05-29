"""Allowlist contract for BaseService.list(order_by=...).

ISSUE-006: without an allowlist, callers can sort on unindexed columns
or columns that leak ordering. The default ``None`` stays permissive
(backwards-compatible); subclasses opt in by setting
``allowed_order_fields``.
"""

from __future__ import annotations

import pytest

from accounts.models import APIKey
from core.base.service import BaseService


class _StrictAPIKeyService(BaseService[APIKey]):
    model = APIKey
    allowed_order_fields = frozenset({"created_at", "name"})


def test_order_by_disallowed_field_raises():
    with pytest.raises(ValueError, match="Ordering by 'prefix' is not allowed"):
        list(_StrictAPIKeyService().list(order_by=["prefix"]))


def test_order_by_descending_form_validated():
    with pytest.raises(ValueError, match="Ordering by '-prefix' is not allowed"):
        list(_StrictAPIKeyService().list(order_by=["-prefix"]))


def test_order_by_allowed_field_passes(user):
    # Returns an empty queryset but does not raise on validation.
    qs = _StrictAPIKeyService().list(order_by=["name", "-created_at"])
    assert list(qs) == []


def test_order_by_unrestricted_when_allowlist_none():
    """Default (allowed_order_fields=None) stays permissive."""

    class _PermissiveAPIKeyService(BaseService[APIKey]):
        model = APIKey

    qs = _PermissiveAPIKeyService().list(order_by=["prefix"])
    assert list(qs) == []
