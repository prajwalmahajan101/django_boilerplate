"""Shared audit-field stamping for service + repository write paths.

``BaseService.create`` / ``update`` and ``BaseRepository.add`` /
``update`` both need to stamp ``created_by`` / ``updated_by`` when the
model carries those fields. Inlining the logic in each method has
drifted twice already, so the single source of truth lives here.
"""

from __future__ import annotations

from typing import Any


def apply_audit_fields(
    instance_or_data: Any,
    user: Any | None,
    *,
    on_create: bool,
) -> None:
    """Stamp ``created_by`` / ``updated_by`` when present on the target.

    Mutates ``instance_or_data`` in place. Accepts either a model
    instance (``setattr``) or a plain ``dict`` (``setdefault``) so the
    same helper covers both ``self.model(**data)`` construction in
    ``BaseService.create`` and direct-instance flows in
    ``BaseRepository``. No-op when ``user`` is falsy or the field is
    absent — callers do not need to introspect the model class.
    """
    if not user:
        return

    is_dict = isinstance(instance_or_data, dict)
    field = "created_by" if on_create else "updated_by"
    _stamp(instance_or_data, field, user, is_dict=is_dict)


def _stamp(target: Any, field: str, user: Any, *, is_dict: bool) -> None:
    if is_dict:
        target.setdefault(field, user)
        return
    if hasattr(target, field):
        setattr(target, field, user)


__all__ = ["apply_audit_fields"]
