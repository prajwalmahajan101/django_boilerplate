"""Validation contract for BaseService writes.

Pinning the contract from ``apps/core/CLAUDE.md``:

- ``create()``  → runs ``full_clean()`` via ``BaseModel.save()``.
- ``update()``  → runs ``full_clean()`` via ``BaseModel.save()``.
- ``bulk_create()`` → runs ``full_clean()`` in an explicit loop, because
  Django's ``QuerySet.bulk_create`` bypasses ``.save()``.

Uses the shipped ``APIKey`` model — a ``BaseModel`` descendant whose
``name`` field is ``max_length=255`` and required.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from accounts.models import APIKey
from core.base.service import BaseService


class APIKeyService(BaseService[APIKey]):
    model = APIKey


def _valid_payload(user, *, name="ci-key", prefix="abcdef12") -> dict:
    """Construct a payload that satisfies every APIKey field constraint."""
    return {
        "user": user,
        "name": name,
        "prefix": prefix,
        "secret": "x" * 32,
    }


def test_create_raises_on_invalid_model(user):
    """``create`` must trip the model's full_clean() — name exceeds max_length."""
    payload = _valid_payload(user, name="x" * 256)
    with pytest.raises(ValidationError):
        APIKeyService().create(payload)


def test_create_succeeds_on_valid_model(user):
    instance = APIKeyService().create(_valid_payload(user))
    assert instance.pk is not None
    assert instance.name == "ci-key"


def test_update_raises_on_invalid_change(user):
    instance = APIKeyService().create(_valid_payload(user))
    with pytest.raises(ValidationError):
        APIKeyService().update(instance.pk, {"name": "x" * 256})


def test_bulk_create_raises_on_invalid_row(user):
    """``bulk_create`` validates explicitly (since it bypasses ``.save()``)."""
    with pytest.raises(ValidationError):
        APIKeyService().bulk_create(
            [
                _valid_payload(user, prefix="aaaaaaaa"),
                _valid_payload(user, prefix="bbbbbbbb", name="x" * 256),
            ]
        )


def test_bulk_create_skips_validation_when_opted_out(user):
    """``validate=False`` is the documented escape hatch for upstream-validated batches."""
    instances = APIKeyService().bulk_create(
        [
            _valid_payload(user, prefix="cccccccc", name="row-1"),
            _valid_payload(user, prefix="dddddddd", name="row-2"),
        ],
        validate=False,
    )
    assert len(instances) == 2
