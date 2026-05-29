"""Tests for ``core.base.repository.BaseRepository`` and ``core.base.schema``."""

from __future__ import annotations

from django.test import TestCase
from rest_framework import serializers

from core.base.repository import BaseRepository
from core.base.schema import BaseSchema


class UserRepository(BaseRepository):
    from django.contrib.auth import get_user_model

    model = get_user_model()


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
