"""``BaseRepository`` — opt-in CRUD facade over the Django ORM.

Django boilerplate uses :class:`BaseService` for the standard
write paths (validation, audit-stamping, soft-delete cascade, hooks).
This module adds a thin sync repository surface that mirrors the
FastAPI sibling's vocabulary (``get_by_id``, ``add``, ``add_all``,
``bulk_update_by_filter``, ``delete_hard``, etc.) so cross-repo
developers see the same verbs.

**Not a replacement** for ``BaseService``. Use this only when a
test or domain class wants ORM access through a thin abstraction
(easier to mock than the manager directly, easier to swap out in
isolation). Production write paths should keep using
``BaseService``.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

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
    def add(cls, instance: ModelType) -> ModelType:
        instance.save()
        return instance

    @classmethod
    @transaction.atomic
    def add_all(cls, instances: list[ModelType]) -> list[ModelType]:
        return list(cls._manager().bulk_create(instances))

    @classmethod
    @transaction.atomic
    def update(cls, pk: Any, data: dict[str, Any]) -> ModelType | None:
        instance = cls._manager().select_for_update().filter(pk=pk).first()
        if instance is None:
            return None
        for key, value in data.items():
            setattr(instance, key, value)
        instance.save()
        return instance

    @classmethod
    @transaction.atomic
    def bulk_update_by_filter(
        cls,
        filters: dict[str, Any],
        data: dict[str, Any],
    ) -> int:
        return cls._manager().filter(**filters).update(**data)

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
