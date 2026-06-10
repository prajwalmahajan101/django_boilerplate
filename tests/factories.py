"""factory-boy factories for test data.

Keep factories thin: just the fields needed for a row to be valid.
Per-test customisation goes in the test, not in the factory. Per-app
factories that depend on app-specific models can subclass these or live
in ``apps/<name>/tests/factories.py``.
"""

from __future__ import annotations

import factory
from django.contrib.auth import get_user_model

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    """Minimal valid user. Override fields per-test as needed."""

    class Meta:
        model = User
        django_get_or_create = ("email",)

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    is_active = True
    is_staff = False
    is_superuser = False

    @factory.post_generation
    def password(obj, create, extracted, **kwargs):  # noqa: N805
        """Set password via ``set_password`` so the hash matches the auth backend.

        Default password is ``"password123"``; override with::

            UserFactory(password="something-else")
        """
        raw = extracted or "password123"
        obj.set_password(raw)
        if create:
            obj.save(update_fields=["password"])
        obj._raw_password = raw  # — handy for login tests
