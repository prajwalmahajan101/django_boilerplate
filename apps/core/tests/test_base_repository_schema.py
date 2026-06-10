"""Tests for ``core.base.repository.BaseRepository`` and ``core.base.schema``."""

from __future__ import annotations

from accounts.models import APIKey
from core.base.repository import BaseRepository
from core.base.schema import BaseSchema
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework import serializers


class UserRepository(BaseRepository):
    from django.contrib.auth import get_user_model

    model = get_user_model()


class APIKeyRepository(BaseRepository):
    model = APIKey


class BaseRepositoryTests(TestCase):
    def test_add_and_get_by_id(self) -> None:
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User(email="alice@example.com", username="alice")
        user.set_password("p@ssw0rd-strong")
        UserRepository.add(user)
        self.assertEqual(UserRepository.get_by_id(user.pk).email, "alice@example.com")

    def test_count_and_filter(self) -> None:
        from django.contrib.auth import get_user_model

        User = get_user_model()
        u = User(email="bob@example.com", username="bob")
        u.set_password("p@ssw0rd-strong")
        UserRepository.add(u)
        self.assertGreaterEqual(UserRepository.count(), 1)
        self.assertTrue(UserRepository.exists(email="bob@example.com"))

    def test_update_and_delete(self) -> None:
        from django.contrib.auth import get_user_model

        User = get_user_model()
        u = User(email="carol@example.com", username="carol")
        u.set_password("p@ssw0rd-strong")
        UserRepository.add(u)
        UserRepository.update(u.pk, {"username": "carol2"})
        self.assertEqual(UserRepository.get_by_id(u.pk).username, "carol2")
        UserRepository.delete_hard_by_id(u.pk)
        self.assertIsNone(UserRepository.get_by_id(u.pk))


class BaseRepositoryAuditFieldsTests(TestCase):
    """Confirm ``add`` / ``add_all`` / ``update`` propagate ``user`` to
    ``created_by`` / ``updated_by`` and run ``full_clean`` on bulk insert.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        from django.contrib.auth import get_user_model

        User = get_user_model()
        cls.alice = User.objects.create_user(
            email="alice@example.com", username="alice", password="p@ssw0rd-strong"
        )
        cls.bob = User.objects.create_user(
            email="bob@example.com", username="bob", password="p@ssw0rd-strong"
        )

    def _make_key(self, prefix: str, name: str = "ci") -> APIKey:
        return APIKey(
            user=self.alice,
            name=name,
            prefix=prefix,
            secret="x" * 32,
        )

    def test_add_stamps_created_by(self) -> None:
        key = self._make_key(prefix="ABCDEFGH")
        APIKeyRepository.add(key, user=self.alice)
        key.refresh_from_db()
        self.assertEqual(key.created_by, self.alice)

    def test_add_all_stamps_created_by_on_every_instance(self) -> None:
        keys = [self._make_key(prefix=f"PR{i:06d}") for i in range(3)]
        APIKeyRepository.add_all(keys, user=self.alice)
        for key in keys:
            key.refresh_from_db()
            self.assertEqual(key.created_by, self.alice)

    def test_add_all_validates_each_instance(self) -> None:
        # An empty ``name`` violates the CharField's blank=False default,
        # so full_clean should raise before bulk_create is reached.
        good = self._make_key(prefix="GOOD1234")
        bad = self._make_key(prefix="BAD12345", name="")
        with self.assertRaises(ValidationError):
            APIKeyRepository.add_all([good, bad], user=self.alice)
        self.assertFalse(APIKey.objects.filter(prefix="GOOD1234").exists())

    def test_update_stamps_updated_by(self) -> None:
        key = self._make_key(prefix="UPDATE01")
        APIKeyRepository.add(key, user=self.alice)
        APIKeyRepository.update(key.pk, {"name": "renamed"}, user=self.bob)
        key.refresh_from_db()
        self.assertEqual(key.updated_by, self.bob)
        self.assertEqual(key.created_by, self.alice)

    def test_omitting_user_leaves_audit_fields_untouched(self) -> None:
        key = self._make_key(prefix="NOUSER01")
        APIKeyRepository.add(key)
        key.refresh_from_db()
        self.assertIsNone(key.created_by)


class SampleSchema(BaseSchema):
    name = serializers.CharField()
    note = serializers.CharField(required=False, allow_blank=True)


class BaseSchemaTests(TestCase):
    def test_drops_empty_on_output(self) -> None:
        s = SampleSchema(instance={"name": "Alice", "note": ""})
        self.assertEqual(s.data, {"name": "Alice"})

    def test_keeps_empty_when_opted_out(self) -> None:
        class KeepingSchema(SampleSchema):
            drop_empty_on_output = False

        s = KeepingSchema(instance={"name": "Alice", "note": ""})
        self.assertEqual(s.data, {"name": "Alice", "note": ""})
