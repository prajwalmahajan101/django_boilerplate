"""``BaseRepository`` — opt-in CRUD facade over the Django ORM.

Django boilerplate uses :class:`BaseService` for the standard
write paths (hooks, soft-delete cascade, …). This module adds a
thin sync repository surface that mirrors the FastAPI sibling's
vocabulary (``get_by_id``, ``add``, ``add_all``, ``update``,
``delete_hard``, etc.) so cross-repo developers see the same verbs.

**Parity with ``BaseService`` — what is and isn't preserved:**

* ✓ ``full_clean()`` model validation runs on every write —
  ``add``/``update`` via :meth:`BaseModel.save`, ``add_all`` via an
  explicit loop (``bulk_create`` bypasses ``.save()``, mirroring
  :meth:`BaseService.bulk_create`).
* ✓ ``created_by`` / ``updated_by`` are stamped via
  :func:`core.base.audit.apply_audit_fields` when the caller passes
  ``user=`` and the model carries the field.
* ✗ ``pre_*`` / ``post_*`` hooks do **not** fire — if you need them,
  use :class:`BaseService`.
* ✗ Soft-delete cascade BFS does **not** run — ``delete_hard`` /
  ``delete_hard_by_id`` are explicit hard deletes.

Bulk-update SQL (``Manager.filter(...).update(...)``) is **not
exposed here on purpose** — it bypasses ``auto_now``,
``updated_by``, validators, and signals, and is the most common
audit-trail regression. Reach through ``cls._manager()`` explicitly
at the call site if you genuinely need that escape hatch, so
reviewers see the bypass.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from core.base.audit import apply_audit_fields
from django.db import models, transaction
from django.db.models import QuerySet

ModelType = TypeVar("ModelType", bound=models.Model)


class BaseRepository(Generic[ModelType]):
    """Generic CRUD facade over a Django model's default manager."""

    model: type[ModelType]

    @classmethod
    def _manager(cls):
        return cls.model._default_manager

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    @classmethod
    def get_by_id(cls, pk: Any) -> ModelType | None:
        return cls._manager().filter(pk=pk).first()

    @classmethod
    def get_active_by_id(cls, pk: Any) -> ModelType | None:
        qs = cls._manager().filter(pk=pk)
        if _has_is_active(cls.model):
            qs = qs.filter(is_active=True)
        return qs.first()

    @classmethod
    def list(cls, *, active_only: bool = True) -> QuerySet[ModelType]:
        qs = cls._manager().all()
        if active_only and _has_is_active(cls.model):
            qs = qs.filter(is_active=True)
        return qs

    @classmethod
    def list_paginated(
        cls,
        *,
        page: int = 1,
        page_size: int = 25,
        active_only: bool = True,
    ) -> tuple[QuerySet[ModelType], int]:
        qs = cls.list(active_only=active_only)
        total = qs.count()
        offset = max(page - 1, 0) * page_size
        return qs[offset : offset + page_size], total

    @classmethod
    def filter(cls, **kwargs: Any) -> QuerySet[ModelType]:
        return cls._manager().filter(**kwargs)

    @classmethod
    def exists(cls, **kwargs: Any) -> bool:
        return cls._manager().filter(**kwargs).exists()

    @classmethod
    def count(cls, **kwargs: Any) -> int:
        qs = cls._manager().all()
        if kwargs:
            qs = qs.filter(**kwargs)
        return qs.count()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def add(cls, instance: ModelType, *, user: Any | None = None) -> ModelType:
        apply_audit_fields(instance, user, on_create=True)
        instance.save()
        return instance

    @classmethod
    @transaction.atomic
    def add_all(
        cls,
        instances: list[ModelType],
        *,
        user: Any | None = None,
    ) -> list[ModelType]:
        for instance in instances:
            apply_audit_fields(instance, user, on_create=True)
            instance.full_clean()
        return list(cls._manager().bulk_create(instances))

    @classmethod
    @transaction.atomic
    def update(
        cls,
        pk: Any,
        data: dict[str, Any],
        *,
        user: Any | None = None,
    ) -> ModelType | None:
        instance = cls._manager().select_for_update().filter(pk=pk).first()
        if instance is None:
            return None
        for key, value in data.items():
            setattr(instance, key, value)
        apply_audit_fields(instance, user, on_create=False)
        instance.save()
        return instance

    @classmethod
    @transaction.atomic
    def delete_hard(cls, instance: ModelType) -> None:
        instance.delete()

    @classmethod
    @transaction.atomic
    def delete_hard_by_id(cls, pk: Any) -> int:
        deleted, _ = cls._manager().filter(pk=pk).delete()
        return deleted


def _has_is_active(model: type[models.Model]) -> bool:
    try:
        model._meta.get_field("is_active")
    except Exception:
        return False
    return True


__all__ = ["BaseRepository"]
