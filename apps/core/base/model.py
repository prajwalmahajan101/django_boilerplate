"""Base models with common audit fields for all project models."""

from django.conf import settings
from django.db import models


class BaseModel(models.Model):
    """Abstract base model with audit fields, soft-delete, and notes.

    Use this for models that do NOT need a human-readable name/code
    (e.g. child entities, config entries, remarks).
    For models that need name + unique code, use ``NamedBaseModel``.
    """

    id = models.BigAutoField(primary_key=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_created",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_updated",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.JSONField(blank=True, null=True)

    def save(self, *args, skip_validation=False, **kwargs):
        """Save with optional model validation via full_clean().

        Set ``skip_validation=True`` when saving from fixtures, management
        commands, or paths where validation is already handled (e.g. the
        service layer calls full_clean() separately).
        """
        if not skip_validation:
            self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.__class__.__name__}(id={self.pk})"

    class Meta:
        abstract = True


class NamedBaseModel(BaseModel):
    """Abstract base model with name and globally unique code.

    Use for top-level reference/domain entities that need a human-readable
    name and a unique identifier (e.g. Partner, Query, Role).
    """

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=100, unique=True)

    def __str__(self) -> str:
        return f"{self.__class__.__name__}(id={self.pk}, code={self.code})"

    class Meta:
        abstract = True
