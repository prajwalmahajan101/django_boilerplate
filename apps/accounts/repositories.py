"""Repositories for auth-related models (User, Role)."""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import QuerySet

from accounts.models import Role

User = get_user_model()


class UserRepository:
    """Repository for User model."""

    model = User

    def get_queryset(self) -> QuerySet:
        return self.model.objects.all()

    def get_by_id(self, pk: int):
        try:
            return self.get_queryset().get(pk=pk)
        except self.model.DoesNotExist:
            return None

    def get_by_email(self, email: str):
        try:
            return self.get_queryset().get(email=email)
        except self.model.DoesNotExist:
            return None

    @transaction.atomic
    def update(self, user_id: int, data: dict):
        """Update a user under a row-level lock.

        Locking lives at the repository so any caller — service, admin
        script, management command — is on the same contract. Callers
        pass the ``user_id``, not a pre-fetched instance, so the lock
        is acquired here under ``@transaction.atomic``.
        """
        user = (
            self.get_queryset()
            .select_for_update()
            .get(pk=user_id)
        )
        for field, value in data.items():
            setattr(user, field, value)
        user.save(update_fields=list(data.keys()))
        return user



class RoleRepository:
    """Repository for Role model."""

    model = Role

    def get_queryset(self) -> QuerySet[Role]:
        return self.model.objects.all()

    def get_or_create(self, name: str, defaults: dict) -> tuple[Role, bool]:
        return self.model.objects.get_or_create(name=name, defaults=defaults)

    def get_default_roles(self) -> QuerySet[Role]:
        return self.get_queryset().filter(is_default=True)

