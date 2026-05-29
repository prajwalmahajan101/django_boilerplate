"""Custom User and Role models for authentication and RBAC."""

import secrets
from functools import cached_property

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import IntegrityError, models
from django.db.models import Q

from accounts.exceptions import APIKeyGenerationError
from accounts.managers import UserManager
from core.base.fields import EncryptedCharField
from core.base.model import BaseModel
from core.enums import Action, Resource


class Permission(models.Model):
    """Granular ACL entry linking a resource to an action.

    Used by ``Role.permissions`` to define what each role can do.
    """

    resource = models.CharField(max_length=100, choices=Resource.choices)
    action = models.CharField(max_length=20, choices=Action.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["resource", "action"],
                name="unique_permission_resource_action",
            ),
            # DB-level enum vetoes — Django's ``choices`` is application-side
            # only, so admin / shell / raw SQL paths could otherwise smuggle
            # in unknown values. Pairs with pattern #69.
            models.CheckConstraint(
                condition=Q(resource__in=Resource.values),
                name="ck_permission_resource",
            ),
            models.CheckConstraint(
                condition=Q(action__in=Action.values),
                name="ck_permission_action",
            ),
        ]
        ordering = ["resource", "action"]

    def __str__(self) -> str:
        return f"{self.resource}:{self.action}"


class Role(models.Model):
    """Role for RBAC. Users can have multiple roles."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_superuser_role = models.BooleanField(
        default=False,
        help_text="Superuser roles have full access to all resources.",
    )
    is_default = models.BooleanField(
        default=False,
        help_text="Default roles are auto-assigned to new users on signup.",
    )
    permissions = models.ManyToManyField(
        Permission,
        blank=True,
        related_name="roles",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class User(AbstractUser):
    """Custom user model extending AbstractUser with roles and profile fields."""

    # Override AbstractUser.email to enforce uniqueness at DB level.
    # allauth's ACCOUNT_UNIQUE_EMAIL is application-layer only; admin, shell,
    # management commands, and direct ORM bypass it.
    email = models.EmailField("email address", unique=True, blank=False)

    avatar_url = models.URLField(max_length=500, blank=True, null=True)
    email_verified = models.BooleanField(default=False)
    roles = models.ManyToManyField(Role, blank=True, related_name="users")
    timezone = models.CharField(max_length=50, default="Asia/Kolkata")
    last_login_ip = models.GenericIPAddressField(blank=True, null=True)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]

    class Meta:
        ordering = ["-date_joined"]

    def __str__(self) -> str:
        return self.email or self.username

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @cached_property
    def has_superuser_role(self) -> bool:
        """Whether the user holds at least one superuser role.

        Cached for the lifetime of this User instance (i.e. one request),
        so multiple permission/throttle checks don't repeat the DB query.
        """
        return self.roles.filter(is_superuser_role=True).exists()


class APIKey(BaseModel):
    """API key for system-to-system authentication.

    Keys are tied to a user and go through the same RBAC permission system.
    The raw key is encrypted at rest using ``EncryptedCharField`` (Fernet).
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="api_keys",
    )
    name = models.CharField(
        max_length=255,
        help_text="Label for this key, e.g. 'Synoriq Production'",
    )
    prefix = models.CharField(
        max_length=8,
        unique=True,
        editable=False,
        db_index=True,
        help_text="First 8 chars of the key, used for lookup.",
    )
    encrypted_key = EncryptedCharField(
        max_length=500,
        editable=False,
        help_text="Full key encrypted at rest via Fernet.",
    )
    last_used_at = models.DateTimeField(null=True, blank=True, editable=False)
    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        help_text=(
            "Set when the key is revoked. Authentication rejects keys with "
            "a non-null revoked_at even if the row is otherwise active. "
            "Soft-revocation is preferred over delete so audit trails stay intact."
        ),
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "API Key"
        verbose_name_plural = "API Keys"

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix}...)"

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @classmethod
    def create_key(cls, *, user, name, created_by=None):
        """Generate a new API key. Returns ``(api_key_instance, raw_key)``.

        The raw key is only available at creation time.
        Retries up to 3 times on prefix collision (astronomically unlikely).
        """
        last_exc = None
        for _ in range(3):
            raw_key = secrets.token_urlsafe(32)
            try:
                api_key = cls(
                    user=user,
                    name=name,
                    prefix=raw_key[:8],
                    encrypted_key=raw_key,
                    created_by=created_by,
                    updated_by=created_by,
                )
                api_key.save()
                return api_key, raw_key
            except IntegrityError as exc:
                last_exc = exc
                continue
        raise APIKeyGenerationError() from last_exc
