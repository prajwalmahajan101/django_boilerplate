"""Admin configuration for the accounts app."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.http import HttpResponse
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from accounts.models import APIKey, Permission, Role, User
from core.base.admin import BaseModelAdmin


@admin.register(User)
class UserAdmin(DjangoUserAdmin, ModelAdmin):
    """Custom UserAdmin with email-based fields and Unfold styling."""

    model = User
    list_display = ("email", "first_name", "last_name", "is_staff", "is_active")
    list_filter = ("is_staff", "is_active", "roles")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)

    fieldsets = (
        (None, {"fields": ("email", "username", "password")}),
        ("Personal Info", {"fields": ("first_name", "last_name", "avatar_url")}),
        (
            "Permissions",
            {
                "description": (
                    "'Staff status' grants Django admin panel access. "
                    "All resource permissions are managed through Roles."
                ),
                "fields": ("is_active", "is_staff", "roles"),
            },
        ),
        (
            "Auth Details",
            {
                "fields": (
                    "email_verified",
                    "timezone",
                    "last_login_ip",
                    "last_login",
                    "date_joined",
                ),
            },
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "username",
                    "password1",
                    "password2",
                    "first_name",
                    "last_name",
                    "is_staff",
                    "is_active",
                    "roles",
                ),
            },
        ),
    )

    readonly_fields = ("date_joined", "last_login", "last_login_ip")
    filter_horizontal = ("roles",)


@admin.register(Permission)
class PermissionAdmin(ModelAdmin):
    """Admin for ACL Permission entries."""

    list_display = ("resource", "action")
    list_filter = ("action",)
    search_fields = ("resource",)
    ordering = ("resource", "action")


@admin.register(Role)
class RoleAdmin(ModelAdmin):
    """Admin for Role model with Unfold styling."""

    list_display = ("name", "is_superuser_role", "is_default", "created_at")
    list_filter = ("is_superuser_role", "is_default")
    search_fields = ("name",)
    ordering = ("name",)
    filter_horizontal = ("permissions",)


@admin.register(APIKey)
class APIKeyAdmin(BaseModelAdmin):
    """Admin for API keys with auto-generation on create."""

    list_display = ("name", "prefix", "user", "is_active", "last_used_at", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "prefix", "user__email")
    ordering = ("-created_at",)
    readonly_fields = ("prefix", "secret", "last_used_at")
    autocomplete_fields = ("user",)

    fieldsets = (
        (None, {"fields": ("user", "name", "is_active")}),
        ("Key Info", {
            "fields": ("prefix", "last_used_at"),
            "classes": ("collapse",),
        }),
    )

    add_fieldsets = (
        (None, {
            "fields": ("user", "name"),
            "description": "A new API key will be auto-generated. "
                           "Copy it from the success message — it won't be shown again.",
        }),
    )

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets
        return super().get_fieldsets(request, obj)

    def get_readonly_fields(self, request, obj=None):
        readonly = set(super().get_readonly_fields(request, obj))
        if obj is not None:
            readonly.add("user")
        return tuple(readonly)

    def save_model(self, request, obj, form, change):
        if not change:
            api_key, raw_key = APIKey.create_key(
                user=form.cleaned_data["user"],
                name=form.cleaned_data["name"],
                created_by=request.user,
            )
            obj.pk = api_key.pk
            # Store on request object (in-memory only) — never persisted
            # to session, cache, or DB. Avoids exposing the raw key in
            # Django's session store which would undermine encryption at rest.
            request._raw_api_key = raw_key
        else:
            obj.updated_by = request.user
            super().save_model(request, obj, form, change)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj)

    def response_add(self, request, obj, post_url_continue=None):
        obj = APIKey.objects.get(pk=obj.pk)
        raw_key = getattr(request, "_raw_api_key", None)
        if raw_key:
            changelist_url = reverse(
                "admin:%s_%s_changelist" % (obj._meta.app_label, obj._meta.model_name),
                current_app=self.admin_site.name,
            )
            return HttpResponse(format_html(
                "<!DOCTYPE html>"
                "<html><head><title>API Key Created</title></head>"
                '<body style="font-family: system-ui, sans-serif; max-width: 600px; '
                'margin: 4em auto; padding: 0 1em;">'
                "<h1>API Key Created</h1>"
                "<p><strong>{name}</strong> ({prefix}...)</p>"
                "<p>Copy this key now &mdash; it will <strong>not</strong> be shown again:</p>"
                '<pre style="background: #f4f4f4; padding: 1em; font-size: 1.1em; '
                'border-radius: 4px; user-select: all; overflow-x: auto;">{key}</pre>'
                '<p><a href="{url}">&larr; Back to API Keys</a></p>'
                "</body></html>",
                name=obj.name,
                prefix=obj.prefix,
                key=raw_key,
                url=changelist_url,
            ))
        return super().response_add(request, obj, post_url_continue)
