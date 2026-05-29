"""Custom authentication backend that delegates permission checks to our RBAC system."""

from __future__ import annotations

from django.contrib.auth.backends import ModelBackend

from core.enums import Action, Resource


class RBACBackend(ModelBackend):
    """Auth backend that maps Django permission checks to Role-based ACL.

    Django admin calls ``user.has_perm("accounts.view_user")``.
    This backend parses that into ``(Resource.ACCOUNT, Action.READ)``
    and checks the User -> Roles -> Permissions chain.

    Superuser-role holders bypass all checks.
    Models not in MODEL_RESOURCE_MAP fall back to denied (safe default).
    Extend MODEL_RESOURCE_MAP per-domain when you add new apps.
    """

    # Django perm prefix -> our Action enum
    PERM_ACTION_MAP: dict[str, str] = {
        "view": Action.READ,
        "add": Action.CREATE,
        "change": Action.UPDATE,
        "delete": Action.DELETE,
    }

    # "app_label.model_name" -> Resource enum value
    MODEL_RESOURCE_MAP: dict[str, str] = {
        "accounts.user": Resource.ACCOUNT,
        "accounts.role": Resource.ROLE,
        "accounts.permission": Resource.ROLE,
        "accounts.apikey": Resource.API_KEY,
    }

    def has_perm(self, user_obj, perm, obj=None):
        """Check if user has a specific permission via RBAC roles.

        Parses Django permission string ``"app_label.action_modelname"``
        (e.g. ``"partners.view_partner"``) into a ``(resource, action)``
        pair and checks against the user's roles.
        """
        if not user_obj.is_active:
            return False

        if getattr(user_obj, "has_superuser_role", False):
            return True

        try:
            app_label, codename = perm.split(".")
            action_prefix, model_name = codename.split("_", 1)
        except ValueError:
            return False

        action = self.PERM_ACTION_MAP.get(action_prefix)
        resource = self.MODEL_RESOURCE_MAP.get(f"{app_label}.{model_name}")

        if not action or not resource:
            return False

        return user_obj.roles.filter(
            permissions__resource=resource,
            permissions__action=action,
        ).exists()

    def has_module_perms(self, user_obj, app_label):
        """Check if user has ANY permission for models in the given app.

        Controls whether the app section appears in the admin sidebar.
        """
        if not user_obj.is_active:
            return False

        if getattr(user_obj, "has_superuser_role", False):
            return True

        app_resources = [
            resource
            for key, resource in self.MODEL_RESOURCE_MAP.items()
            if key.startswith(f"{app_label}.")
        ]

        if not app_resources:
            return False

        return user_obj.roles.filter(
            permissions__resource__in=app_resources,
        ).exists()
