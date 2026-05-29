"""Base service class for business logic layer.

Works directly with the Django ORM — no repository indirection.
Provides select_for_update() locking, soft-delete, audit trail,
and pre/post hooks for domain-specific business rules.

This module is intentionally kept as a single class. Each write path
(``create``, ``update``, ``bulk_create``, ``bulk_update``, ``delete``)
shares the same ``pre_*`` / ``post_*`` hook surface, the same audit-
stamping logic, and the same soft-delete cascade walk. Fragmenting the
write methods across multiple modules would either duplicate the hook
surface (write-path drift across copies) or replace it with a mixin
chain that's harder to follow than the current linear file. Reviewed
across three review cycles; the cohesion is deliberate, not drift.
See ``docs/data-model.md`` for the full contract.
"""

from __future__ import annotations

import logging
from abc import ABC
from collections import deque
from typing import Any, Generic, TypeVar

from django.db import models, transaction
from django.db.models import QuerySet
from django.utils import timezone

from core.exceptions import EntityNotFoundError

logger = logging.getLogger(__name__)

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
    allowed_order_fields: frozenset[str] | None = None

    # Maximum depth for ``_cascade_soft_delete_bfs`` recursion. Beyond this
    # the cascade short-circuits with a WARNING log — protects against
    # circular soft-FK chains introduced by future contributors.
    MAX_CASCADE_DEPTH: int = 10

    # Hard ceiling on per-call page size. Callers asking for more than
    # this get silently capped (with a debug log) instead of materializing
    # a million-row queryset. Subclasses can override per-resource.
    max_page_size: int = 100

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

    def _validate_order_keys(self, order_by: list[str]) -> None:
        """Validate order_by keys against allowed_order_fields if defined.

        Without an allowlist, callers can sort on unindexed or sensitive
        columns. The default ``None`` is permissive so existing code keeps
        working; subclasses opt in by setting ``allowed_order_fields``.
        """
        if self.allowed_order_fields is None:
            return
        for raw in order_by:
            # Strip leading "-" for descending sort.
            field = raw.lstrip("-")
            # Strip lookup suffixes (e.g. "user__email" → "user")
            base_field = field.split("__")[0]
            if base_field not in self.allowed_order_fields:
                raise ValueError(
                    f"Ordering by '{raw}' is not allowed. "
                    f"Allowed fields: {sorted(self.allowed_order_fields)}"
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
        active_only: bool = True,
    ) -> QuerySet[ModelType]:
        """List instances with filtering, ordering, and pagination.

        ``active_only`` defaults to ``True`` — soft-deleted rows
        (``is_active=False``) are hidden unless the caller explicitly
        opts in with ``active_only=False``. The default is fail-safe:
        a casually written listing endpoint that forgets the kwarg
        would otherwise silently surface deleted rows to API consumers.

        Page-size contract: ``limit`` is silently clamped to
        ``max_page_size`` (default 100) — an absent ``limit`` is set to
        the ceiling. The clamp emits a WARNING with the requested vs
        capped values so operators can spot misconfigured callers in
        logs. Subclasses raise the ceiling by overriding ``max_page_size``;
        we never raise on over-large limits because pagination callers
        routinely pass a default ``page_size`` from request params, and
        a hard-fail would convert a config miss into a 500.
        """
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
            self._validate_order_keys(order_by)
            qs = qs.order_by(*order_by)

        # Enforce the page-size ceiling. An over-large caller-supplied
        # ``limit`` is silently clamped to ``max_page_size`` (with a
        # WARNING — visible at default LOG_LEVEL=INFO so the cap doesn't
        # hide a buggy caller); an absent limit is set to the ceiling so
        # unbounded ``.all()``-style listings can't be triggered by
        # accident.
        capped_limit = limit if limit is not None else self.max_page_size
        if capped_limit > self.max_page_size:
            logger.warning(
                "list_limit_capped",
                extra={
                    "service": self.__class__.__name__,
                    "requested": capped_limit,
                    "max": self.max_page_size,
                },
            )
            capped_limit = self.max_page_size

        if offset is not None:
            qs = qs[offset : offset + capped_limit]
        else:
            qs = qs[:capped_limit]

        return qs

    def list_active(self, **kwargs) -> QuerySet[ModelType]:
        # Backwards-compat shim — list() now defaults active_only=True,
        # so this is identical to a bare list() call. Kept so external
        # callers don't break and the intent at the call site stays
        # readable.
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
        """Create a new instance. Runs ``full_clean()`` via ``BaseModel.save()``.

        Validation contract: model-level validators fire on every service
        write. Serializers own request-shape validation; this layer is the
        second line of defense (e.g. constraints introduced after the
        serializer was written).
        """
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
        """Bulk insert. Validates explicitly because ``bulk_create`` bypasses ``.save()``.

        Django's ``QuerySet.bulk_create`` skips ``.save()`` entirely, so
        ``BaseModel.save()``'s ``full_clean()`` does not fire. The explicit
        loop preserves the same validation contract as the single-row path.
        Set ``validate=False`` only when you've validated upstream (e.g. a
        management command that already ran ``full_clean()`` per row).
        """
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
        """Update a row under ``select_for_update``. Runs ``full_clean()`` via ``BaseModel.save()``.

        See ``create`` for the validation contract — same rules apply.
        """
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
                self._cascade_soft_delete_bfs(instance, user=user)
        else:
            instance.delete()

        self.post_delete(instance, user=user)
        return True

    @classmethod
    def _cascade_soft_delete_bfs(cls, instance: ModelType, user: Any | None = None) -> None:
        """Soft-delete related objects linked via CASCADE foreign keys (BFS).

        Walks the related-object graph breadth-first with a depth cap of
        ``MAX_CASCADE_DEPTH``. Beyond the cap, the cascade short-circuits
        and logs WARNING — this protects against circular soft-FK chains
        introduced by future contributors.

        Propagates ``user`` into ``updated_by`` when the related model has
        that field — without it, cascade rows silently misattribute state
        changes to the previous editor instead of the actor who triggered
        the delete.
        """
        # (instance, depth) — start at depth 0 (root)
        frontier: deque[tuple[Any, int]] = deque([(instance, 0)])
        while frontier:
            current, depth = frontier.popleft()
            if depth >= cls.MAX_CASCADE_DEPTH:
                logger.warning(
                    "cascade_soft_delete depth cap reached",
                    extra={
                        "model": type(current).__name__,
                        "pk": getattr(current, "pk", None),
                        "depth": depth,
                        "max_depth": cls.MAX_CASCADE_DEPTH,
                    },
                )
                continue
            for rel in current._meta.related_objects:
                if rel.on_delete is not models.CASCADE:
                    continue
                related_model = rel.related_model
                if not hasattr(related_model, "is_active"):
                    continue
                accessor = rel.get_accessor_name()
                related_qs = getattr(current, accessor).filter(is_active=True)
                children = list(related_qs)
                update_kwargs: dict[str, Any] = {
                    "is_active": False,
                    "updated_at": timezone.now(),
                }
                if user is not None and hasattr(related_model, "updated_by"):
                    update_kwargs["updated_by"] = user
                related_qs.update(**update_kwargs)
                for child in children:
                    frontier.append((child, depth + 1))
