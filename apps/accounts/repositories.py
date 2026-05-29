"""Repositories for auth-related models (User, Role)."""

from django.contrib.auth import get_user_model
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

    def update(self, user, data: dict):
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

