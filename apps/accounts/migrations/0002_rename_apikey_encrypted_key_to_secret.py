"""Rename ``APIKey.encrypted_key`` to ``APIKey.secret``.

The old name was misleading: ``EncryptedCharField.from_db_value`` decrypts
on read, so accessing ``api_key.encrypted_key`` returned plaintext — not
ciphertext as the name suggested. The new name describes the read-side
observable: a secret value. The column rename is metadata only; no data
is rewritten and the field type / encryption-at-rest behaviour is unchanged.
"""

import core.base.fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RenameField(
            model_name="apikey",
            old_name="encrypted_key",
            new_name="secret",
        ),
        migrations.AlterField(
            model_name="apikey",
            name="secret",
            field=core.base.fields.EncryptedCharField(
                editable=False,
                help_text="Encrypted at rest via Fernet; decrypted to plaintext on read.",
                max_length=500,
            ),
        ),
    ]
