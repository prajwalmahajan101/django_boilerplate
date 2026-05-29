"""Tests for API key authentication."""

from unittest.mock import patch

from django.core.cache import caches
from django.test import RequestFactory, TestCase
from rest_framework.exceptions import AuthenticationFailed

from accounts.authentication import APIKeyAuthentication
from accounts.models import APIKey, User


class APIKeyModelTest(TestCase):
    """Tests for the APIKey model."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="service@example.com",
            password="testpass123",
        )
        self.api_key, self.raw_key = APIKey.create_key(
            user=self.user, name="Test Key",
        )

    def test_create_key_returns_instance_and_raw_key(self):
        self.assertIsInstance(self.api_key, APIKey)
        self.assertIsInstance(self.raw_key, str)
        self.assertGreaterEqual(len(self.raw_key), 32)

    def test_prefix_matches_raw_key_start(self):
        self.assertEqual(self.api_key.prefix, self.raw_key[:8])

    def test_secret_decrypts_to_raw_key(self):
        self.api_key.refresh_from_db()
        self.assertEqual(self.api_key.secret, self.raw_key)

    def test_create_key_sets_updated_by(self):
        api_key, _ = APIKey.create_key(
            user=self.user, name="Audit Key", created_by=self.user,
        )
        self.assertEqual(api_key.updated_by, self.user)

    def test_is_active_defaults_to_true(self):
        self.assertTrue(self.api_key.is_active)

    def test_str_representation(self):
        text = str(self.api_key)
        self.assertIn(self.api_key.name, text)
        self.assertIn(self.api_key.prefix, text)

    def test_prefix_is_unique(self):
        _, key2 = APIKey.create_key(user=self.user, name="Key 2")
        self.assertNotEqual(self.raw_key[:8], key2[:8])

    def test_cascade_delete_with_user(self):
        pk = self.api_key.pk
        self.user.delete()
        self.assertFalse(APIKey.objects.filter(pk=pk).exists())


class APIKeyAuthenticationTest(TestCase):
    """Tests for the APIKeyAuthentication DRF backend."""

    def setUp(self):
        self.rf = RequestFactory()
        self.auth = APIKeyAuthentication()
        self.user = User.objects.create_user(
            email="service@example.com",
            password="testpass123",
        )
        self.api_key, self.raw_key = APIKey.create_key(
            user=self.user, name="Test Key",
        )

    def test_no_header_returns_none(self):
        """Missing X-API-Key header lets other auth classes try."""
        request = self.rf.get("/")
        self.assertIsNone(self.auth.authenticate(request))

    def test_valid_key_authenticates(self):
        request = self.rf.get("/", HTTP_X_API_KEY=self.raw_key)
        result_user, result_auth = self.auth.authenticate(request)
        self.assertEqual(result_user, self.user)
        self.assertIsInstance(result_auth, APIKey)

    def test_tampered_key_raises(self):
        request = self.rf.get("/", HTTP_X_API_KEY=self.raw_key + "tampered")
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)

    def test_bogus_key_raises(self):
        """A completely bogus key with no matching prefix."""
        request = self.rf.get(
            "/", HTTP_X_API_KEY="bogus_key_that_doesnt_exist_at_all",
        )
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)

    def test_short_key_raises(self):
        request = self.rf.get("/", HTTP_X_API_KEY="short")
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)

    def test_deactivated_key_raises(self):
        self.api_key.is_active = False
        self.api_key.save(skip_validation=True)

        request = self.rf.get("/", HTTP_X_API_KEY=self.raw_key)
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)

    def test_inactive_user_raises(self):
        inactive = User.objects.create_user(
            email="inactive@example.com",
            password="testpass123",
            is_active=False,
        )
        _, raw_key = APIKey.create_key(user=inactive, name="Inactive Key")

        request = self.rf.get("/", HTTP_X_API_KEY=raw_key)
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)

    def test_last_used_at_updated(self):
        self.assertIsNone(self.api_key.last_used_at)

        request = self.rf.get("/", HTTP_X_API_KEY=self.raw_key)
        self.auth.authenticate(request)

        self.api_key.refresh_from_db()
        self.assertIsNotNone(self.api_key.last_used_at)

    def test_authenticate_header(self):
        request = self.rf.get("/")
        self.assertEqual(self.auth.authenticate_header(request), "X-API-Key")

    def test_request_auth_is_api_key_instance(self):
        request = self.rf.get("/", HTTP_X_API_KEY=self.raw_key)
        _, result_auth = self.auth.authenticate(request)
        self.assertEqual(result_auth.pk, self.api_key.pk)

    def test_last_used_at_debounced(self):
        """Second auth within 5 minutes skips the DB write (cache hit)."""
        debounce_cache = caches["rate_limit"]
        debounce_cache.clear()

        # First auth — cache miss, writes last_used_at
        request = self.rf.get("/", HTTP_X_API_KEY=self.raw_key)
        self.auth.authenticate(request)

        # Verify cache key was set on the rate_limit alias
        cache_key = f"apikey_used_{self.api_key.pk}"
        self.assertTrue(debounce_cache.get(cache_key))
