"""Custom authentication backend that delegates permission checks to our RBAC system."""

from __future__ import annotations

from core.enums import Action
from core.rbac_registry import app_resources, resource_for
from django.contrib.auth.backends import ModelBackend


class RBACBackend(ModelBackend):
    """Auth backend that maps Django permission checks to Role-based ACL.

    Django admin calls ``user.has_perm("accounts.view_user")``.
    This backend parses that into ``(Resource.ACCOUNT, Action.READ)``
    and checks the User -> Roles -> Permissions chain.

    Superuser-role holders bypass all checks.
    Models without a registered Resource fall back to denied (safe
    default). Domain apps register their own mappings via
    ``core.rbac_registry.register_resource()`` from ``AppConfig.ready()``
    — no edit to this file is needed when adding a new app.
    """

    # Django perm prefix -> our Action enum
    PERM_ACTION_MAP: dict[str, str] = {
        "view": Action.READ,
        "add": Action.CREATE,
        "change": Action.UPDATE,
        "delete": Action.DELETE,
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
        resource = resource_for(app_label, model_name)

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

        resources = app_resources(app_label)
        if not resources:
            return False

        return user_obj.roles.filter(
            permissions__resource__in=resources,
        ).exists()
