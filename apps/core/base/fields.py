"""Custom model fields.

``EncryptedCharField`` is now provided by ``resilience-kit``; re-exported
here so existing imports (``from core.base.fields import EncryptedCharField``)
and the lookup-limitation contract documented in
``apps/accounts/models.py: APIKey.secret`` keep working.
"""

from resilience_kit.adapters.django.fields import EncryptedCharField

__all__ = ["EncryptedCharField"]
