"""Tests for ``accounts.permissions.is_superuser_role``."""

from __future__ import annotations

from unittest.mock import MagicMock

from accounts.permissions import is_superuser_role


def test_returns_false_for_anonymous_user():
    user = MagicMock()
    user.is_authenticated = False
    user.has_superuser_role = True  # would matter if path didn't short-circuit
    assert is_superuser_role(user) is False


def test_returns_true_when_user_has_superuser_role():
    user = MagicMock()
    user.is_authenticated = True
    user.has_superuser_role = True
    assert is_superuser_role(user) is True


def test_returns_false_when_authenticated_but_no_superuser_role():
    user = MagicMock()
    user.is_authenticated = True
    user.has_superuser_role = False
    assert is_superuser_role(user) is False
