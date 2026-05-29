"""RBAC permissions for access control.

Centralised RBAC helpers used by DRF permission classes and views.
"""

from __future__ import annotations

from accounts.models import User


def is_superuser_role(user: User) -> bool:
    """Check if the user holds at least one superuser role.

    Uses the cached_property on the User model to avoid repeated queries.
    """
    if not user.is_authenticated:
        return False
    return user.has_superuser_role
