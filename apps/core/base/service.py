"""Base service class for business logic layer.

Works directly with the Django ORM — no repository indirection.
Provides select_for_update() locking, soft-delete, audit trail,
and pre/post hooks for domain-specific business rules.
"""

from __future__ import annotations

from abc import ABC
from typing import Any, Generic, TypeVar

from django.db import models, transaction
from django.db.models import QuerySet
from django.utils import timezone

from core.exceptions import EntityNotFoundError

ModelType = TypeVar("ModelType", bound=models.Model)


class BaseService(ABC, Generic[ModelType]):
    """Base service operating directly on a Django model.

    Usage::

        class ProductService(BaseService[Product]):
            model = Product

            def pre_create(self, data, user=None):
                data["sku"] = generate_sku(data["name"])
                return data
    """

    model: type[ModelType]
    allowed_filter_fields: frozenset[str] | None = None

    # ------------------------------------------------------------------
    # Queryset
    # ------------------------------------------------------------------

    def get_queryset(self) -> QuerySet[ModelType]:
        """Return the base queryset."""
        return self.model.objects.all()

    def _validate_filter_keys(self, filters: dict[str, Any]) -> None:
        """Validate filter keys against allowed_filter_fields if defined."""
        if self.allowed_filter_fields is None:
            return
        for key in filters:
            # Strip lookup suffixes (e.g. "name__icontains" → "name")
            base_field = key.split("__")[0]
            if base_field not in self.allowed_filter_fields:
                raise ValueError(
                    f"Filter on '{key}' is not allowed. "
                    f"Allowed fields: {sorted(self.allowed_filter_fields)}"
                )

    # ------------------------------------------------------------------
    # Hooks — override in subclasses for business rules
    # ------------------------------------------------------------------

    def pre_create(
        self, data: dict[str, Any], user: Any | None = None
    ) -> dict[str, Any]:
        return data

    def post_create(self, instance: ModelType, user: Any | None = None) -> None:
        pass

    def pre_update(
        self, instance: ModelType, data: dict[str, Any], user: Any | None = None
    ) -> dict[str, Any]:
        return data

    def post_update(self, instance: ModelType, user: Any | None = None) -> None:
        pass

    def pre_delete(self, instance: ModelType) -> None:
        pass

    def post_delete(self, instance: ModelType, user: Any | None = None) -> None:
        pass

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_by_id(self, pk: int) -> ModelType | None:
        try:
            return self.get_queryset().get(pk=pk)
        except self.model.DoesNotExist:
            return None

    def get_by_id_or_fail(self, pk: int) -> ModelType:
        instance = self.get_by_id(pk)
        if not instance:
            raise EntityNotFoundError(self.model.__name__, pk)
        return instance

    def get_active_by_id(self, pk: int) -> ModelType | None:
        try:
            return self.get_queryset().get(pk=pk, is_active=True)
        except self.model.DoesNotExist:
            return None

    def get_active_by_id_or_fail(self, pk: int) -> ModelType:
        instance = self.get_active_by_id(pk)
        if not instance:
            raise EntityNotFoundError(self.model.__name__, pk)
        return instance

    def list(
        self,
        filters: dict[str, Any] | None = None,
        order_by: list[str] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        select_related: list[str] | None = None,
        prefetch_related: list[str] | None = None,
        active_only: bool = False,
    ) -> QuerySet[ModelType]:
        """List instances with filtering, ordering, and pagination."""
        qs = self.get_queryset()

        if select_related:
            qs = qs.select_related(*select_related)
        if prefetch_related:
            qs = qs.prefetch_related(*prefetch_related)

        if active_only:
            filters = filters or {}
            filters["is_active"] = True
        if filters:
            self._validate_filter_keys(filters)
            qs = qs.filter(**filters)

        if order_by:
            qs = qs.order_by(*order_by)

        if offset is not None and limit is not None:
            qs = qs[offset : offset + limit]
        elif offset is not None:
            qs = qs[offset:]
        elif limit is not None:
            qs = qs[:limit]

        return qs

    def list_active(self, **kwargs) -> QuerySet[ModelType]:
        return self.list(active_only=True, **kwargs)

    def filter(self, **kwargs) -> QuerySet[ModelType]:
        self._validate_filter_keys(kwargs)
        return self.get_queryset().filter(**kwargs)

    def exists(self, **kwargs) -> bool:
        self._validate_filter_keys(kwargs)
        return self.get_queryset().filter(**kwargs).exists()

    def count(self, filters: dict[str, Any] | None = None) -> int:
        qs = self.get_queryset()
        if filters:
            self._validate_filter_keys(filters)
            qs = qs.filter(**filters)
        return qs.count()

    # ------------------------------------------------------------------
    # Write operations (with hooks + locking + audit trail)
    # ------------------------------------------------------------------

    @transaction.atomic
    def create(self, data: dict[str, Any], user: Any | None = None) -> ModelType:
        data = self.pre_create(data, user)

        if user and hasattr(self.model, "created_by"):
            data.setdefault("created_by", user)

        instance = self.model(**data)
        instance.save()

        self.post_create(instance, user)
        return instance

    @transaction.atomic
    def bulk_create(
        self,
        data_list: list[dict[str, Any]],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        validate: bool = True,
    ) -> list[ModelType]:
        instances = [self.model(**data) for data in data_list]

        if validate:
            for instance in instances:
                instance.full_clean()

        return self.model.objects.bulk_create(
            instances, batch_size=batch_size, ignore_conflicts=ignore_conflicts
        )

    @transaction.atomic
    def update(
        self,
        pk: int,
        data: dict[str, Any],
        user: Any | None = None,
        active_only: bool = True,
    ) -> ModelType | None:
        qs = self.get_queryset().select_for_update().filter(pk=pk)
        if active_only:
            qs = qs.filter(is_active=True)

        instance = qs.first()
        if not instance:
            return None

        data = self.pre_update(instance, data, user)

        for field, value in data.items():
            setattr(instance, field, value)

        if user and hasattr(instance, "updated_by"):
            instance.updated_by = user

        instance.save()

        self.post_update(instance, user)
        return instance

    @transaction.atomic
    def update_or_fail(
        self,
        pk: int,
        data: dict[str, Any],
        user: Any | None = None,
        active_only: bool = True,
    ) -> ModelType:
        instance = self.update(pk, data, user=user, active_only=active_only)
        if not instance:
            raise EntityNotFoundError(self.model.__name__, pk)
        return instance

    @transaction.atomic
    def bulk_update(
        self,
        instances: list[ModelType],
        fields: list[str],
        batch_size: int | None = None,
        validate: bool = True,
    ) -> None:
        if validate:
            for instance in instances:
                instance.full_clean()

        self.model.objects.bulk_update(instances, fields, batch_size=batch_size)

    @transaction.atomic
    def delete(
        self,
        pk: int,
        soft: bool = True,
        active_only: bool = True,
        cascade_soft_delete: bool = True,
        user: Any | None = None,
    ) -> bool:
        qs = self.get_queryset().select_for_update().filter(pk=pk)
        if active_only:
            qs = qs.filter(is_active=True)

        instance = qs.first()
        if not instance:
            return False

        self.pre_delete(instance)

        if soft and hasattr(instance, "is_active"):
            instance.is_active = False
            update_fields = ["is_active", "updated_at"]
            if user and hasattr(instance, "updated_by"):
                instance.updated_by = user
                update_fields.append("updated_by_id")
            instance.save(update_fields=update_fields)

            if cascade_soft_delete:
                self._cascade_soft_delete(instance, user=user)
        else:
            instance.delete()

        self.post_delete(instance, user=user)
        return True

    @staticmethod
    def _cascade_soft_delete(instance: ModelType, user: Any | None = None) -> None:
        """Recursively soft-delete related objects linked via CASCADE foreign keys.

        Propagates ``user`` into ``updated_by`` when the related model has that
        field — without it, cascade rows silently misattribute state changes to
        the previous editor instead of the actor who triggered the delete.
        """
        for rel in instance._meta.related_objects:
            if rel.on_delete is not models.CASCADE:
                continue
            related_model = rel.related_model
            if not hasattr(related_model, "is_active"):
                continue
            accessor = rel.get_accessor_name()
            related_qs = getattr(instance, accessor).filter(is_active=True)
            children = list(related_qs)
            update_kwargs: dict[str, Any] = {
                "is_active": False,
                "updated_at": timezone.now(),
            }
            if user is not None and hasattr(related_model, "updated_by"):
                update_kwargs["updated_by"] = user
            related_qs.update(**update_kwargs)
            for child in children:
                BaseService._cascade_soft_delete(child, user=user)
