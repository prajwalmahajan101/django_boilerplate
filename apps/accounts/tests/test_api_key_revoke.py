"""Tests for APIKey soft-revoke.

Pin the full lifecycle: create → use → revoke → next use returns 401.
ISSUE-227 — also pin ``APIKeyService.revoke``'s contract since the view
now delegates to it.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from accounts.authentication import APIKeyAuthentication
from accounts.models import APIKey, User
from accounts.services import APIKeyService
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed


class APIKeyRevokeTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(email="revoke@test.example.com", password="x")
        self.api_key, self.raw_key = APIKey.create_key(
            user=self.user,
            name="test-key",
            created_by=self.user,
        )
        self.auth = APIKeyAuthentication()

    def _request(self):
        req = MagicMock()
        req.META = {"HTTP_X_API_KEY": self.raw_key}
        return req

    def test_active_key_authenticates(self) -> None:
        user, _ = self.auth.authenticate(self._request())
        self.assertEqual(user.pk, self.user.pk)

    def test_revoked_key_returns_401(self) -> None:
        self.api_key.revoked_at = timezone.now()
        self.api_key.save(update_fields=["revoked_at"])
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(self._request())

    def test_revoked_property_reflects_state(self) -> None:
        self.assertFalse(self.api_key.is_revoked)
        self.api_key.revoked_at = timezone.now()
        self.assertTrue(self.api_key.is_revoked)


class APIKeyServiceRevokeTests(TestCase):
    """ISSUE-227 — service-layer contract for the revoke state transition."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(email="svc-revoke@test.example.com", password="x")
        self.api_key, _ = APIKey.create_key(
            user=self.user,
            name="svc-test-key",
            created_by=self.user,
        )

    def test_first_revoke_returns_revoked_now(self) -> None:
        revoked_now, already = APIKeyService().revoke(self.api_key.pk, user=self.user)
        self.assertTrue(revoked_now)
        self.assertFalse(already)
        self.api_key.refresh_from_db()
        self.assertIsNotNone(self.api_key.revoked_at)
        self.assertEqual(self.api_key.updated_by_id, self.user.id)

    def test_second_revoke_is_idempotent_and_preserves_timestamp(self) -> None:
        """Idempotent revoke: second call must not overwrite the original timestamp."""
        APIKeyService().revoke(self.api_key.pk, user=self.user)
        self.api_key.refresh_from_db()
        original_revoked_at = self.api_key.revoked_at

        revoked_now, already = APIKeyService().revoke(self.api_key.pk, user=self.user)
        self.assertFalse(revoked_now)
        self.assertTrue(already)
        self.api_key.refresh_from_db()
        # Timestamp from the original revoke is preserved — race-safe.
        self.assertEqual(self.api_key.revoked_at, original_revoked_at)

    def test_revoke_missing_key_returns_not_found(self) -> None:
        revoked_now, already = APIKeyService().revoke(99999, user=self.user)
        self.assertFalse(revoked_now)
        self.assertFalse(already)

    def test_revoke_soft_deleted_key_returns_not_found(self) -> None:
        """Inactive keys are out of scope — service returns the not-found tuple."""
        self.api_key.is_active = False
        self.api_key.save(update_fields=["is_active", "updated_at"])

        revoked_now, already = APIKeyService().revoke(self.api_key.pk, user=self.user)
        self.assertFalse(revoked_now)
        self.assertFalse(already)
