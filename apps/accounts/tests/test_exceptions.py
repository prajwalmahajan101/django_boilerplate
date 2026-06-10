"""Tests for typed account-domain exceptions.

Verifies that:
  * ``APIKey.create_key`` raises ``APIKeyGenerationError`` (not bare
    ``RuntimeError``) when prefix collisions exhaust the retry loop.
  * The cause chain (``__cause__``) preserves the underlying
    ``IntegrityError`` for diagnostics.
"""

from unittest.mock import patch

from accounts.exceptions import APIKeyGenerationError
from accounts.models import APIKey, User
from django.db import IntegrityError
from django.test import TestCase


class APIKeyGenerationErrorTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="collision@example.com",
            password="testpass123",
        )

    def test_raises_typed_exception_after_retry_exhaustion(self):
        # Force every save to raise IntegrityError so the retry loop
        # exhausts and the error path triggers.
        with patch.object(APIKey, "save", side_effect=IntegrityError("dup prefix")):
            with self.assertRaises(APIKeyGenerationError) as ctx:
                APIKey.create_key(user=self.user, name="collide")

        # Underlying IntegrityError is preserved for diagnostics.
        self.assertIsInstance(ctx.exception.__cause__, IntegrityError)

    def test_error_code_is_auto_derived(self):
        # _derive_error_code() drops the trailing "Error" and snake-cases.
        with patch.object(APIKey, "save", side_effect=IntegrityError("dup")):
            try:
                APIKey.create_key(user=self.user, name="collide")
            except APIKeyGenerationError as exc:
                self.assertEqual(exc.get_error_code(), "API_KEY_GENERATION")
