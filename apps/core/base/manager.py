"""Shared QuerySet + Manager helpers for soft-deletable models.

Most domain models carry an ``is_active`` flag for soft-delete. The
``.active()`` filter is repeated across every service and view; this
module centralises it so callers don't need to remember the column name.

Usage::

    from core.base.manager import SoftDeletableQuerySet

    class Partner(NamedBaseModel):
        objects = SoftDeletableQuerySet.as_manager()
        ...

    Partner.objects.active()  # is_active=True
    Partner.objects.inactive()  # is_active=False

Adoption is intentionally **incremental** — wiring every model in one
commit is risky. New services should prefer ``.active()`` over inline
``filter(is_active=True)`` so the conversion happens organically.
"""

from __future__ import annotations

from django.db import models


class SoftDeletableQuerySet(models.QuerySet):
    """QuerySet with ``.active()`` / ``.inactive()`` convenience methods.

    Requires the model to declare an ``is_active`` BooleanField. Calling
    ``.active()`` against a model without the column raises
    ``FieldError`` at queryset evaluation — preferred over a silent
    no-op because the missed filter would mask deleted rows.
    """

    def active(self) -> SoftDeletableQuerySet:
        return self.filter(is_active=True)

    def inactive(self) -> SoftDeletableQuerySet:
        return self.filter(is_active=False)


__all__ = ["SoftDeletableQuerySet"]
