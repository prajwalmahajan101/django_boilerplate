"""Unit tests for ``apps.accounts.backends.RBACBackend``.

Drives the backend with ``MagicMock`` users + monkeypatched registry
helpers; no DB. Mirrors the unit-tier shape from
``apps/core/tests/test_permissions.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from accounts.backends import RBACBackend


def _user(*, active=True, superuser=False, role_match=False):
    """Build a mock user with the duck-typed surface RBACBackend uses."""
    user = MagicMock()
    user.is_active = active
    user.has_superuser_role = superuser
    user.roles.filter.return_value.exists.return_value = role_match
    return user


@pytest.fixture
def backend():
    return RBACBackend()


# ---------- has_perm ------------------------------------------------------


def test_has_perm_returns_false_for_inactive_user(backend):
    assert backend.has_perm(_user(active=False), "accounts.view_user") is False


def test_has_perm_short_circuits_for_superuser_role(backend):
    user = _user(superuser=True)
    assert backend.has_perm(user, "accounts.view_user") is True
    user.roles.filter.assert_not_called()


def test_has_perm_returns_false_for_perm_string_without_dot(backend):
    assert backend.has_perm(_user(), "view_user") is False


def test_has_perm_returns_false_for_codename_without_underscore(backend):
    assert backend.has_perm(_user(), "accounts.view") is False


def test_has_perm_returns_false_for_unknown_action_prefix(backend, monkeypatch):
    monkeypatch.setattr(
        "accounts.backends.resource_for", lambda app, model: "ACCOUNT"
    )
    assert backend.has_perm(_user(), "accounts.frobnicate_user") is False


def test_has_perm_returns_false_for_unregistered_resource(backend, monkeypatch):
    monkeypatch.setattr("accounts.backends.resource_for", lambda app, model: None)
    assert backend.has_perm(_user(), "accounts.view_user") is False


def test_has_perm_returns_true_when_role_matches(backend, monkeypatch):
    monkeypatch.setattr(
        "accounts.backends.resource_for", lambda app, model: "ACCOUNT"
    )
    user = _user(role_match=True)
    assert backend.has_perm(user, "accounts.view_user") is True


def test_has_perm_returns_false_when_role_does_not_match(backend, monkeypatch):
    monkeypatch.setattr(
        "accounts.backends.resource_for", lambda app, model: "ACCOUNT"
    )
    user = _user(role_match=False)
    assert backend.has_perm(user, "accounts.view_user") is False


# ---------- has_module_perms ---------------------------------------------


def test_has_module_perms_returns_false_for_inactive_user(backend):
    assert backend.has_module_perms(_user(active=False), "accounts") is False


def test_has_module_perms_short_circuits_for_superuser_role(backend):
    user = _user(superuser=True)
    assert backend.has_module_perms(user, "accounts") is True
    user.roles.filter.assert_not_called()


def test_has_module_perms_returns_false_for_app_without_resources(
    backend, monkeypatch
):
    monkeypatch.setattr("accounts.backends.app_resources", lambda app: [])
    assert backend.has_module_perms(_user(), "ghost") is False


def test_has_module_perms_returns_true_when_role_matches(backend, monkeypatch):
    monkeypatch.setattr(
        "accounts.backends.app_resources", lambda app: ["ACCOUNT", "ROLE"]
    )
    user = _user(role_match=True)
    assert backend.has_module_perms(user, "accounts") is True


def test_has_module_perms_returns_false_when_role_does_not_match(
    backend, monkeypatch
):
    monkeypatch.setattr(
        "accounts.backends.app_resources", lambda app: ["ACCOUNT"]
    )
    user = _user(role_match=False)
    assert backend.has_module_perms(user, "accounts") is False
