"""``BaseSchema`` — opt-in DRF serializer base with parity defaults.

Mirrors the FastAPI sibling's ``BaseSchema(BaseModel)`` defaults
(populate by name, strip-whitespace) so cross-repo developers can use
the same vocabulary. This is **opt-in**: existing serializers may
continue to subclass ``serializers.Serializer`` /
``serializers.ModelSerializer`` directly.
"""

from __future__ import annotations

from rest_framework import serializers


class BaseSchema(serializers.Serializer):
    """DRF serializer base with strip-whitespace + clean-empty defaults.

    * Subclasses inherit ``CharField.trim_whitespace=True`` semantics
      (DRF's default — kept explicit here).
    * ``to_representation`` strips ``None`` / empty-string values so
      response payloads stay tight. Override on a subclass to disable.
    """

    drop_empty_on_output: bool = True

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self.drop_empty_on_output:
            return data
        return {k: v for k, v in data.items() if v not in (None, "")}


class BaseModelSchema(serializers.ModelSerializer):
    """``ModelSerializer`` counterpart to :class:`BaseSchema`."""

    drop_empty_on_output: bool = True

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self.drop_empty_on_output:
            return data
        return {k: v for k, v in data.items() if v not in (None, "")}


__all__ = ["BaseModelSchema", "BaseSchema"]
