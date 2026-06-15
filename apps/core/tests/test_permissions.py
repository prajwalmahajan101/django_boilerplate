"""Tests for ``core.permissions`` and the RBAC registry helpers.

Covers ``HasResourcePermission`` (DRF permission class) plus the
``user_has_permission`` free-function path. Stays at the unit tier —
exercises decision branches with mock users / requests / views rather
than driving the full DB-backed role/permission chain (that's covered
in ``apps/accounts/tests/test_api_key_auth.py`` and friends).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from core.permissions import HasResourcePermission, user_has_permission
from core.rbac_registry import (
    _RESOURCE_FOR_MODEL,
    _lock,
    app_resources,
    register_resource,
    registered_mappings,
    resource_for,
)

# ---------- HasResourcePermission ----------------------------------------


class _View:
    """Minimal stand-in for a DRF view declaring resource + action."""

    def __init__(self, resource=None, action=None):
        self.resource = resource
        self.action = action


def _user(*, authenticated=True, superuser=False, role_match=False):
    """Mock user matching the duck-typing ``user_has_permission`` expects."""
    user = MagicMock()
    user.is_authenticated = authenticated
    user.has_superuser_role = superuser
    user.roles.filter.return_value.exists.return_value = role_match
    return user


def _request(user):
    """Minimal request with a ``user`` attribute and no permission cache."""
    return SimpleNamespace(user=user)


def test_has_permission_returns_false_when_view_missing_resource():
    perm = HasResourcePermission()
    request = _request(_user())
    view = _View(resource=None, action="READ")
    assert perm.has_permission(request, view) is False


def test_has_permission_returns_false_when_view_missing_action():
    perm = HasResourcePermission()
    request = _request(_user())
    view = _View(resource="ACCOUNT", action=None)
    assert perm.has_permission(request, view) is False


def test_has_permission_returns_false_when_user_anonymous():
    perm = HasResourcePermission()
    request = _request(_user(authenticated=False))
    view = _View(resource="ACCOUNT", action="READ")
    assert perm.has_permission(request, view) is False


def test_has_permission_short_circuits_for_superuser():
    perm = HasResourcePermission()
    user = _user(superuser=True)
    request = _request(user)
    view = _View(resource="ACCOUNT", action="DELETE")
    assert perm.has_permission(request, view) is True
    # Superuser path must not consult the role table.
    user.roles.filter.assert_not_called()


def test_has_permission_returns_true_when_role_matches():
    perm = HasResourcePermission()
    request = _request(_user(role_match=True))
    view = _View(resource="ACCOUNT", action="READ")
    assert perm.has_permission(request, view) is True


def test_has_permission_returns_false_when_role_does_not_match():
    perm = HasResourcePermission()
    request = _request(_user(role_match=False))
    view = _View(resource="ACCOUNT", action="READ")
    assert perm.has_permission(request, view) is False


# ---------- user_has_permission cache ------------------------------------


def test_user_has_permission_caches_per_request():
    user = _user(role_match=True)
    request = _request(user)
    user_has_permission(user, "ACCOUNT", "READ", request=request)
    user_has_permission(user, "ACCOUNT", "READ", request=request)
    # Second call should hit the cache — one DB lookup total.
    assert user.roles.filter.call_count == 1
    assert request._permission_cache == {("ACCOUNT", "READ"): True}


def test_user_has_permission_distinct_keys_dont_collide_in_cache():
    user = _user(role_match=True)
    request = _request(user)
    user_has_permission(user, "ACCOUNT", "READ", request=request)
    user_has_permission(user, "ROLE", "READ", request=request)
    assert user.roles.filter.call_count == 2
    assert ("ACCOUNT", "READ") in request._permission_cache
    assert ("ROLE", "READ") in request._permission_cache


def test_user_has_permission_without_request_skips_cache():
    user = _user(role_match=True)
    # Two calls, no request → no cache, two DB hits.
    user_has_permission(user, "ACCOUNT", "READ")
    user_has_permission(user, "ACCOUNT", "READ")
    assert user.roles.filter.call_count == 2


def test_user_has_permission_anonymous_returns_false():
    user = _user(authenticated=False)
    assert user_has_permission(user, "ACCOUNT", "READ") is False
    user.roles.filter.assert_not_called()


def test_user_has_permission_none_user_returns_false():
    assert user_has_permission(None, "ACCOUNT", "READ") is False


# ---------- core.rbac_registry -------------------------------------------


@pytest.fixture
def isolated_resource_registry():
    """Snapshot + restore the resource registry around each test."""
    with _lock:
        snapshot = dict(_RESOURCE_FOR_MODEL)
        _RESOURCE_FOR_MODEL.clear()
    yield
    with _lock:
        _RESOURCE_FOR_MODEL.clear()
        _RESOURCE_FOR_MODEL.update(snapshot)


def test_register_and_lookup(isolated_resource_registry):
    register_resource("accounts.user", "ACCOUNT")
    assert resource_for("accounts", "user") == "ACCOUNT"
    assert resource_for("ACCOUNTS", "User") == "ACCOUNT"  # case-insensitive


def test_register_is_idempotent(isolated_resource_registry):
    register_resource("accounts.user", "ACCOUNT")
    register_resource("accounts.user", "ACCOUNT")  # same → no-op
    assert registered_mappings() == {"accounts.user": "ACCOUNT"}


def test_register_collision_raises(isolated_resource_registry):
    register_resource("accounts.user", "ACCOUNT")
    with pytest.raises(ValueError, match="already mapped"):
        register_resource("accounts.user", "ROLE")


def test_resource_for_returns_none_when_unregistered(isolated_resource_registry):
    assert resource_for("accounts", "ghost") is None


def test_app_resources_returns_only_matching_app(isolated_resource_registry):
    register_resource("accounts.user", "ACCOUNT")
    register_resource("accounts.role", "ROLE")
    register_resource("billing.invoice", "INVOICE")
    assert sorted(app_resources("accounts")) == ["ACCOUNT", "ROLE"]
    assert app_resources("billing") == ["INVOICE"]
    assert app_resources("missing") == []


def test_registered_mappings_returns_copy(isolated_resource_registry):
    register_resource("accounts.user", "ACCOUNT")
    snap = registered_mappings()
    snap["mutated"] = "BAD"
    # Original registry must not be affected.
    assert "mutated" not in registered_mappings()


# ---------- core.registries re-exports -----------------------------------


def test_registries_package_reexports_match_implementation():
    """The package-level façade must keep its public API stable."""
    from core import registries

    assert registries.register_resource is register_resource
    assert registries.resource_for is resource_for
    assert registries.app_resources is app_resources
    assert registries.registered_mappings is registered_mappings
    # ``register_resilience_service`` is bound at import time from the
    # resilience-kit singleton; just assert the attribute exists and is
    # callable so a future rename in the kit doesn't silently drop it.
    assert callable(registries.register_resilience_service)
    assert registries.resilience_registry is not None
