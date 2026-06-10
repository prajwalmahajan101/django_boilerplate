"""Base admin classes with Unfold styling and automatic audit field handling."""

from core.base.widgets import JsonEditorWidget
from django.contrib.contenttypes.admin import GenericTabularInline
from django.db import models
from unfold.admin import ModelAdmin, TabularInline


class BaseModelAdmin(ModelAdmin):
    """ModelAdmin that auto-populates created_by/updated_by from the logged-in user.

    Inherits from ``unfold.admin.ModelAdmin`` for proper Unfold theme styling.
    Adds audit timestamps and user fields as readonly in a collapsible
    "Audit Trail" fieldset. Subclasses that define ``fieldsets`` should
    include ``audit_fieldset`` (or it will be appended automatically).

    All JSONField fields automatically use the JSON editor widget.
    """

    formfield_overrides = {
        models.JSONField: {"widget": JsonEditorWidget},
    }

    audit_fieldset = (
        "Audit Trail",
        {
            "fields": (
                "created_by",
                "updated_by",
                "created_at",
                "updated_at",
            ),
            "classes": ("collapse",),
        },
    )

    def get_readonly_fields(self, request, obj=None):
        readonly = set(super().get_readonly_fields(request, obj))
        readonly |= {"created_by", "updated_by", "created_at", "updated_at"}
        return tuple(readonly)

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        audit_fields = {"created_by", "updated_by", "created_at", "updated_at"}
        already_present = any(audit_fields & set(fs[1].get("fields", ())) for fs in fieldsets)
        if not already_present:
            fieldsets = list(fieldsets) + [self.audit_fieldset]
        return fieldsets

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


class BaseTabularInline(TabularInline):
    """Base tabular inline with Unfold styling.

    Provides audit field handling consistent with ``BaseModelAdmin``.
    """

    readonly_fields = ("created_by", "updated_by", "created_at", "updated_at")
    extra = 0


class BaseGenericTabularInline(GenericTabularInline, TabularInline):
    """Generic-FK tabular inline with Unfold styling.

    MRO order matters: ``GenericTabularInline`` first (provides the
    content_type/object_id queryset wiring), then Unfold's ``TabularInline``
    (provides templates and CSS classes). Without the latter, the inline
    renders with stock Django chrome inside an otherwise-themed page.
    """

    readonly_fields = ("created_by", "updated_by", "created_at", "updated_at")
    extra = 0
