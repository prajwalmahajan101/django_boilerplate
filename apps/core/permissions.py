"""ACL-based DRF permission classes for resource-level access control."""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission


def user_has_permission(
    user: Any,
    resource: Any,
    action: Any,
    *,
    request: Any | None = None,
) -> bool:
    """Canonical resource/action permission check.

    Single source of truth for "does *user* hold (resource, action)?".
    Used by :class:`HasResourcePermission` and by call sites that need
    to enforce a permission outside DRF's view-level pipeline (synthetic
    write fields on serializers, admin-side checks, cross-resource attach
    flows). The same per-request cache shape is reused when *request* is
    supplied so DRF's view-level check and any in-handler check share
    cache entries instead of duplicating DB hits.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "has_superuser_role", False):
        return True

    if request is not None:
        cache = getattr(request, "_permission_cache", None)
        if cache is None:
            cache = {}
            request._permission_cache = cache
        cache_key = (resource, action)
        if cache_key in cache:
            return cache[cache_key]
        result = user.roles.filter(
            permissions__resource=resource,
            permissions__action=action,
        ).exists()
        cache[cache_key] = result
        return result

    return user.roles.filter(
        permissions__resource=resource,
        permissions__action=action,
    ).exists()


class HasResourcePermission(BasePermission):
    """Check that the authenticated user has the required resource permission.

    Views declare which resource and action they guard::

        class UserListCreateView(APIView):
            resource = Resource.ACCOUNT
            action = Action.READ     # overridden per HTTP method in initial()

    The permission walks **User -> Roles -> Permissions** and checks for a
    matching ``(resource, action)`` pair.  Users with a superuser role
    bypass the ACL entirely.

    Results are cached per (resource, action) on the request object to
    avoid repeated DB queries within the same request.
    """

    def has_permission(self, request, view):
        resource = getattr(view, "resource", None)
        action = getattr(view, "action", None)
        if not resource or not action:
            return False
        return user_has_permission(request.user, resource, action, request=request)
