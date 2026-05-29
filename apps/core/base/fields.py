"""Custom model fields."""

import base64
import functools
import hashlib
import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models

from cryptography.fernet import Fernet, InvalidToken

from core.exceptions.infrastructure import InfrastructureError

logger = logging.getLogger(__name__)


class DecryptionError(InfrastructureError):
    """Raised when an encrypted field cannot be decrypted."""

    default_message = "Failed to decrypt field value."
    error_code = "DECRYPTION_ERROR"


@functools.lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """Derive a Fernet key from FIELD_ENCRYPTION_KEY (required in prod).

    A dedicated ``FIELD_ENCRYPTION_KEY`` keeps routine SECRET_KEY rotation
    from silently corrupting encrypted data. In DEBUG environments only we
    fall back to SECRET_KEY with a warning so local development and tests
    without a separate key still work. In production the absence of
    ``FIELD_ENCRYPTION_KEY`` is a configuration error and we refuse to
    boot — better a loud failure than a silent data-corruption window on
    the next SECRET_KEY rotation.
    """
    key_source = getattr(settings, "FIELD_ENCRYPTION_KEY", None)
    if not key_source:
        if not settings.DEBUG:
            raise ImproperlyConfigured(
                "FIELD_ENCRYPTION_KEY must be set in non-DEBUG environments. "
                "Silent fallback to SECRET_KEY is disabled to prevent data "
                "corruption on SECRET_KEY rotation."
            )
        logger.warning(
            "FIELD_ENCRYPTION_KEY not set; falling back to SECRET_KEY "
            "(DEBUG only)."
        )
        key_source = settings.SECRET_KEY
    key_bytes = hashlib.sha256(key_source.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key_bytes))


class EncryptedCharField(models.CharField):
    """CharField that encrypts values at rest using Fernet (AES-128-CBC).

    The underlying DB column remains a CharField (no schema change needed
    beyond increasing max_length to accommodate ciphertext overhead).
    Plaintext is encrypted before saving and decrypted on read.

    Empty strings and None are stored as-is (not encrypted).
    """

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if not value:
            return value
        return _get_fernet().encrypt(value.encode()).decode()

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        try:
            return _get_fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            logger.error(
                "EncryptedCharField decryption failed — possible key rotation or data corruption. "
                "Field value will be unusable until re-encrypted with the correct key.",
                exc_info=True,
            )
            raise DecryptionError(
                "Failed to decrypt field value. Check FIELD_ENCRYPTION_KEY configuration."
            )

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        return name, "core.base.fields.EncryptedCharField", args, kwargs
