"""Tests for ``apps.accounts.adapters``.

Mix of DB-backed tests (save_user / role assignment — the parts that
touch our extensions, not allauth internals) and pure mock tests
(pre_social_login + populate_user, which are easier to drive with a
``MagicMock`` sociallogin than to spin up a real allauth state).

Risks per the M2.5 plan:
- allauth superclass internals are private; tests stay narrow and
  patch the super().save_user call so we exercise OUR additions
  (role assignment, IP capture, populate_user fields) without
  re-testing allauth.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from accounts.adapters import (
    CustomAccountAdapter,
    CustomSocialAccountAdapter,
    assign_default_roles,
    role_repository,
)
from accounts.models import Role
from tests.factories import UserFactory


@pytest.fixture
def user_factory(db):
    """Local re-export so co-located adapter tests don't need ``tests/conftest.py``."""

    def _make(**overrides):
        return UserFactory(**overrides)

    return _make


# ---------- assign_default_roles -----------------------------------------


@pytest.mark.django_db
def test_assign_default_roles_warns_when_no_defaults(user_factory, caplog):
    user = user_factory()
    # No Role rows exist with is_default=True -> warning path.
    with caplog.at_level("WARNING", logger="accounts.adapters"):
        assign_default_roles(user)
    assert any(
        "No default roles configured" in rec.message for rec in caplog.records
    )
    assert user.roles.count() == 0


@pytest.mark.django_db
def test_assign_default_roles_attaches_default_roles(user_factory, caplog):
    Role.objects.create(name="default-user", is_default=True)
    Role.objects.create(name="non-default", is_default=False)
    user = user_factory()

    with caplog.at_level("INFO", logger="accounts.adapters"):
        assign_default_roles(user)

    role_names = set(user.roles.values_list("name", flat=True))
    assert role_names == {"default-user"}
    assert any("Assigned default roles" in r.message for r in caplog.records)


# ---------- CustomAccountAdapter.save_user --------------------------------


@pytest.mark.django_db
def test_account_adapter_save_user_commit_assigns_roles(user_factory):
    role = Role.objects.create(name="default-user", is_default=True)
    adapter = CustomAccountAdapter()
    user = user_factory()

    with patch.object(
        adapter.__class__.__bases__[0],
        "save_user",
        return_value=user,
    ) as super_save:
        out = adapter.save_user(request=None, user=user, form=None, commit=True)

    super_save.assert_called_once()
    assert out is user
    assert role in user.roles.all()


@pytest.mark.django_db
def test_account_adapter_save_user_no_commit_skips_role_assignment(user_factory):
    Role.objects.create(name="default-user", is_default=True)
    adapter = CustomAccountAdapter()
    user = user_factory()
    # Detach existing roles so we can assert nothing got added.
    user.roles.clear()

    with patch.object(
        adapter.__class__.__bases__[0],
        "save_user",
        return_value=user,
    ):
        adapter.save_user(request=None, user=user, form=None, commit=False)

    assert user.roles.count() == 0


# ---------- CustomSocialAccountAdapter.pre_social_login -------------------


def test_pre_social_login_returns_early_when_account_already_linked():
    adapter = CustomSocialAccountAdapter()
    sociallogin = MagicMock()
    sociallogin.is_existing = True
    request = MagicMock()
    adapter.pre_social_login(request, sociallogin)
    sociallogin.connect.assert_not_called()


def test_pre_social_login_returns_early_when_no_email_in_extra_data():
    adapter = CustomSocialAccountAdapter()
    sociallogin = MagicMock()
    sociallogin.is_existing = False
    sociallogin.account.extra_data = {}
    adapter.pre_social_login(MagicMock(), sociallogin)
    sociallogin.connect.assert_not_called()


@pytest.mark.django_db
def test_pre_social_login_connects_to_existing_active_user(user_factory):
    existing = user_factory(email="dup@example.com", is_active=True)
    adapter = CustomSocialAccountAdapter()
    sociallogin = MagicMock()
    sociallogin.is_existing = False
    sociallogin.account.extra_data = {"email": "dup@example.com"}
    request = MagicMock()

    adapter.pre_social_login(request, sociallogin)

    sociallogin.connect.assert_called_once_with(request, existing)


@pytest.mark.django_db
def test_pre_social_login_does_not_connect_inactive_user(user_factory):
    user_factory(email="dup@example.com", is_active=False)
    adapter = CustomSocialAccountAdapter()
    sociallogin = MagicMock()
    sociallogin.is_existing = False
    sociallogin.account.extra_data = {"email": "dup@example.com"}

    adapter.pre_social_login(MagicMock(), sociallogin)

    sociallogin.connect.assert_not_called()


@pytest.mark.django_db
def test_pre_social_login_does_not_connect_when_no_user_matches():
    adapter = CustomSocialAccountAdapter()
    sociallogin = MagicMock()
    sociallogin.is_existing = False
    sociallogin.account.extra_data = {"email": "ghost@example.com"}

    adapter.pre_social_login(MagicMock(), sociallogin)

    sociallogin.connect.assert_not_called()


# ---------- CustomSocialAccountAdapter.populate_user ----------------------


def test_populate_user_copies_picture_and_email_verified():
    adapter = CustomSocialAccountAdapter()
    sociallogin = MagicMock()
    sociallogin.account.extra_data = {
        "picture": "https://lh3.googleusercontent.com/avatar",
        "email_verified": True,
    }
    user = MagicMock()

    with patch.object(
        adapter.__class__.__bases__[0],
        "populate_user",
        return_value=user,
    ) as super_populate:
        out = adapter.populate_user(MagicMock(), sociallogin, {})

    super_populate.assert_called_once()
    assert out is user
    assert user.avatar_url == "https://lh3.googleusercontent.com/avatar"
    assert user.email_verified is True


def test_populate_user_defaults_when_extra_data_missing_keys():
    adapter = CustomSocialAccountAdapter()
    sociallogin = MagicMock()
    sociallogin.account.extra_data = {}
    user = MagicMock()

    with patch.object(
        adapter.__class__.__bases__[0],
        "populate_user",
        return_value=user,
    ):
        adapter.populate_user(MagicMock(), sociallogin, {})

    assert user.avatar_url == ""
    assert user.email_verified is False


# ---------- CustomSocialAccountAdapter.save_user --------------------------


@pytest.mark.django_db
def test_social_save_user_captures_real_client_ip(user_factory):
    Role.objects.create(name="default-user", is_default=True)
    adapter = CustomSocialAccountAdapter()
    user = user_factory()
    request = MagicMock()

    with (
        patch.object(
            adapter.__class__.__bases__[0],
            "save_user",
            return_value=user,
        ),
        patch("core.utils.network.client_ip", return_value="203.0.113.7"),
    ):
        out = adapter.save_user(request, MagicMock())

    user.refresh_from_db()
    assert out.last_login_ip == "203.0.113.7"
    assert user.roles.filter(name="default-user").exists()


@pytest.mark.django_db
def test_social_save_user_skips_ip_when_unknown(user_factory):
    Role.objects.create(name="default-user", is_default=True)
    adapter = CustomSocialAccountAdapter()
    user = user_factory(last_login_ip=None)

    with (
        patch.object(
            adapter.__class__.__bases__[0],
            "save_user",
            return_value=user,
        ),
        patch("core.utils.network.client_ip", return_value="unknown"),
    ):
        adapter.save_user(MagicMock(), MagicMock())

    user.refresh_from_db()
    assert user.last_login_ip is None


@pytest.mark.django_db
def test_social_save_user_skips_ip_when_empty(user_factory):
    Role.objects.create(name="default-user", is_default=True)
    adapter = CustomSocialAccountAdapter()
    user = user_factory(last_login_ip=None)

    with (
        patch.object(
            adapter.__class__.__bases__[0],
            "save_user",
            return_value=user,
        ),
        patch("core.utils.network.client_ip", return_value=""),
    ):
        adapter.save_user(MagicMock(), MagicMock())

    user.refresh_from_db()
    assert user.last_login_ip is None


@pytest.mark.django_db
def test_social_save_user_rolls_back_on_role_assignment_failure(user_factory):
    """A failure in role assignment must roll back the IP write."""
    adapter = CustomSocialAccountAdapter()
    user = user_factory(last_login_ip=None)

    with (
        patch.object(
            adapter.__class__.__bases__[0],
            "save_user",
            return_value=user,
        ),
        patch("core.utils.network.client_ip", return_value="203.0.113.9"),
        patch.object(
            role_repository,
            "get_default_roles",
            side_effect=RuntimeError("boom"),
        ),
        pytest.raises(RuntimeError),
    ):
        adapter.save_user(MagicMock(), MagicMock())

    user.refresh_from_db()
    assert user.last_login_ip is None
