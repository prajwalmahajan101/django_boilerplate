"""Field-level Fernet encryption (AES-128-CBC + HMAC).

Single source of truth for ``EncryptedCharField`` and any code that
needs round-trip plaintext ↔ ciphertext outside the ORM. The Fernet
instance is cached process-wide via ``functools.lru_cache`` so every
encrypt/decrypt call reuses the same key without re-deriving the
SHA-256 digest.

Key derivation:
    * ``settings.FIELD_ENCRYPTION_KEY`` is hashed with SHA-256 and the
      digest is used as the Fernet key. A dedicated key means routine
      rotation of any other secret cannot accidentally corrupt
      encrypted columns.
    * Under ``DEBUG=True`` only, falls back to ``SECRET_KEY`` with a
      warning so local development without a key still boots.
    * In non-DEBUG, the absence of ``FIELD_ENCRYPTION_KEY`` is a
      configuration error — refuse to encrypt rather than silently
      produce data nobody can read after the next key rotation.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import logging

from django.conf import settings

from core.exceptions.infrastructure import InfrastructureError

logger = logging.getLogger(__name__)


class FernetUnavailableError(InfrastructureError):
    """``cryptography`` is not installed (Fernet cannot be loaded)."""

    default_message = "Fernet encryption library is not available."
    error_code = "FERNET_UNAVAILABLE"


class EncryptionConfigError(InfrastructureError):
    """``FIELD_ENCRYPTION_KEY`` missing in a non-DEBUG environment."""

    default_message = "FIELD_ENCRYPTION_KEY must be set in non-DEBUG environments."
    error_code = "ENCRYPTION_CONFIG_ERROR"


class DecryptionError(InfrastructureError):
    """Raised when an encrypted value cannot be decrypted."""

    default_message = "Failed to decrypt field value."
    error_code = "DECRYPTION_ERROR"


@functools.lru_cache(maxsize=1)
def _fernet():
    """Return the process-wide ``Fernet`` instance, building it on first call."""
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise FernetUnavailableError() from exc

    key_source = getattr(settings, "FIELD_ENCRYPTION_KEY", None)
    if not key_source:
        if not getattr(settings, "DEBUG", False):
            raise EncryptionConfigError(
                "FIELD_ENCRYPTION_KEY must be set in non-DEBUG environments. "
                "Silent fallback to SECRET_KEY is disabled to prevent data "
                "corruption on SECRET_KEY rotation."
            )
        logger.warning(
            "FIELD_ENCRYPTION_KEY not set; falling back to SECRET_KEY (DEBUG only)."
        )
        key_source = getattr(settings, "SECRET_KEY", None)
        if not key_source:
            raise EncryptionConfigError(
                "Neither FIELD_ENCRYPTION_KEY nor SECRET_KEY is set."
            )
    digest = hashlib.sha256(key_source.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def reset_cache() -> None:
    """Drop the cached Fernet instance. Test helper."""
    _fernet.cache_clear()


class FernetCipher:
    """Encrypt/decrypt strings with the application's Fernet key."""

    @staticmethod
    def encrypt(plaintext: str) -> str:
        """Encrypt ``plaintext`` with the configured Fernet key.

        Empty strings pass through unchanged so they survive a round
        trip without forcing a sentinel value in the database.
        """
        if not plaintext:
            return plaintext
        return _fernet().encrypt(plaintext.encode()).decode()

    @staticmethod
    def decrypt(ciphertext: str) -> str:
        """Decrypt ``ciphertext`` with the configured Fernet key.

        Empty strings pass through unchanged. ``InvalidToken`` is
        converted into :class:`DecryptionError` so callers can map it
        onto a 5xx response without exposing crypto internals.
        """
        if not ciphertext:
            return ciphertext
        try:
            from cryptography.fernet import InvalidToken
        except ImportError as exc:
            raise FernetUnavailableError() from exc
        try:
            return _fernet().decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            logger.error(
                "Fernet decryption failed — possible key rotation or data corruption."
            )
            raise DecryptionError(
                "Failed to decrypt value. Check FIELD_ENCRYPTION_KEY configuration."
            ) from exc
