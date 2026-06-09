"""Tests for ``apps.core.utils.crypto``."""

from __future__ import annotations

from core.utils import crypto
from core.utils.crypto import (
    DecryptionError,
    EncryptionConfigError,
    FernetCipher,
)
from django.test import TestCase, override_settings


class FernetCipherTests(TestCase):
    def setUp(self) -> None:
        crypto.reset_cache()

    def tearDown(self) -> None:
        crypto.reset_cache()

    def test_roundtrip(self) -> None:
        cipher = FernetCipher.encrypt("hello world")
        self.assertNotEqual(cipher, "hello world")
        self.assertEqual(FernetCipher.decrypt(cipher), "hello world")

    def test_empty_string_passes_through(self) -> None:
        self.assertEqual(FernetCipher.encrypt(""), "")
        self.assertEqual(FernetCipher.decrypt(""), "")

    def test_invalid_token_raises_decryption_error(self) -> None:
        with self.assertRaises(DecryptionError):
            FernetCipher.decrypt("not-a-fernet-token")

    @override_settings(FIELD_ENCRYPTION_KEY=None, DEBUG=False)
    def test_missing_key_in_non_debug_raises(self) -> None:
        crypto.reset_cache()
        with self.assertRaises(EncryptionConfigError):
            FernetCipher.encrypt("hello")
