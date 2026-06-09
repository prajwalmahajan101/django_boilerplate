"""Custom model fields."""

import logging

from core.utils.crypto import DecryptionError, _fernet
from cryptography.fernet import InvalidToken
from django.db import models

logger = logging.getLogger(__name__)


class EncryptedCharField(models.CharField):
    """CharField that encrypts values at rest using Fernet (AES-128-CBC).

    The underlying DB column remains a CharField (no schema change needed
    beyond increasing max_length to accommodate ciphertext overhead).
    Plaintext is encrypted before saving and decrypted on read.

    Empty strings and None are stored as-is (not encrypted).

    Lookup limitation — read this before adding the field to a new model.
    Fernet uses a fresh random IV per encryption, so two encryptions of
    the same plaintext produce different ciphertext. Equality lookups
    against the column (``.filter(field=plaintext)``) re-encrypt the
    filter value with a *new* IV and will silently never match. There
    is no supported way to look up a row by an encrypted value.

    The pattern to use when you need lookup by an encrypted value is a
    sidecar lookup column: store the first N characters as an indexed
    plaintext column and resolve the full value with a constant-time
    compare. See ``APIKey.prefix`` / ``APIKey.secret`` in
    ``apps/accounts/models.py`` for the worked example — ``prefix`` is
    an 8-char indexed lookup column with a partial covering index;
    ``APIKeyAuthentication`` resolves the row by prefix then verifies
    the full key with ``secrets.compare_digest``.
    """

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if not value:
            return value
        return _fernet().encrypt(value.encode()).decode()

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        try:
            return _fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            logger.error(
                "EncryptedCharField decryption failed — possible key rotation or data corruption. "
                "Field value will be unusable until re-encrypted with the correct key.",
                exc_info=True,
            )
            raise DecryptionError(
                "Failed to decrypt field value. Check FIELD_ENCRYPTION_KEY configuration."
            ) from None

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        return name, "core.base.fields.EncryptedCharField", args, kwargs
