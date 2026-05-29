"""Custom allauth adapters for user creation and social login."""

from __future__ import annotations

import logging

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.db import transaction

from accounts.repositories import RoleRepository

logger = logging.getLogger(__name__)

role_repository = RoleRepository()


def assign_default_roles(user) -> None:
    """Assign default roles to a newly created user.

    Shared utility called by both account and social adapters.
    """
    default_roles = role_repository.get_default_roles()
    if default_roles.exists():
        user.roles.add(*default_roles)
        logger.info(
            "Assigned default roles to user %s: %s",
            user.email,
            list(default_roles.values_list("name", flat=True)),
        )
    else:
        logger.warning(
            "No default roles configured — user %s created without RBAC roles.",
            user.email,
        )


class CustomAccountAdapter(DefaultAccountAdapter):
    """Custom account adapter that assigns default roles to new users."""

    def save_user(self, request, user, form, commit=True):
        """Save user and assign default RBAC roles on commit.

        Wraps user creation and role assignment in a single transaction
        so that a failure in role assignment rolls back the user creation,
        preventing users from existing without roles.
        """
        with transaction.atomic():
            user = super().save_user(request, user, form, commit=commit)
            if commit:
                assign_default_roles(user)
        return user


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Custom social account adapter for Google OAuth."""

    def pre_social_login(self, request, sociallogin):
        """Link social account to existing user with same email."""
        if sociallogin.is_existing:
            return

        email = sociallogin.account.extra_data.get("email")
        if not email:
            return

        from accounts.repositories import UserRepository

        user_repository = UserRepository()
        existing_user = user_repository.get_by_email(email)
        if existing_user and existing_user.is_active:
            sociallogin.connect(request, existing_user)

    def populate_user(self, request, sociallogin, data):
        """Set avatar and email_verified from Google profile data."""
        user = super().populate_user(request, sociallogin, data)
        extra_data = sociallogin.account.extra_data

        user.avatar_url = extra_data.get("picture", "")
        user.email_verified = extra_data.get("email_verified", False)

        return user

    def save_user(self, request, sociallogin, form=None):
        """Save user with default roles and last login IP.

        Wraps user creation, IP tracking, and role assignment in a single
        transaction so that a failure in role assignment rolls back the
        user creation, preventing users from existing without roles.
        """
        with transaction.atomic():
            user = super().save_user(request, sociallogin, form)

            # Only read X-Forwarded-For when running behind a trusted proxy.
            # Without this check, any client can forge their last_login_ip.
            from django.conf import settings as django_settings

            if getattr(django_settings, "USE_X_FORWARDED_FOR", False):
                ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
            else:
                ip = None
            if not ip:
                ip = request.META.get("REMOTE_ADDR")
            if ip:
                user.last_login_ip = ip
                user.save(update_fields=["last_login_ip"])

            assign_default_roles(user)

        return user
