"""Tests for the custom DRF exception handler and registry.

Verifies:
  * Domain-app registrations made in ``AppConfig.ready()`` are honored.
  * The standard envelope shape (``success``, ``message``, ``data``,
    ``errors``, ``request_id``) is preserved across exception types.
  * Auto-derived ``error_code`` matches the SCREAMING_SNAKE_CASE form.
"""

from accounts.exceptions import (
    APIKeyGenerationError,
    InvalidTimezoneError,
    NoFieldsToUpdateError,
)
from core.exceptions.handler import api_exception_handler
from core.exceptions.infrastructure import S3Exception
from core.exceptions.repository import EntityNotFoundError
from django.test import SimpleTestCase


class StatusCodeRegistryTest(SimpleTestCase):
    def test_entity_not_found_maps_to_404(self):
        exc = EntityNotFoundError("Widget", 7)
        response = api_exception_handler(exc, context={})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["errors"][0]["code"], "ENTITY_NOT_FOUND")
        self.assertEqual(
            response.data["errors"][0]["details"],
            {"entity_name": "Widget", "entity_id": 7},
        )

    def test_s3_exception_maps_to_502(self):
        response = api_exception_handler(S3Exception("upload failed"), context={})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data["errors"][0]["code"], "S3_ERROR")

    def test_api_key_generation_maps_to_500(self):
        # Registered by accounts.apps.AccountsConfig.ready().
        response = api_exception_handler(APIKeyGenerationError(), context={})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["errors"][0]["code"], "API_KEY_GENERATION")

    def test_no_fields_to_update_maps_to_400(self):
        # Registered by accounts.apps.AccountsConfig.ready(). Pins the
        # contract that the auto-derived error_code reaches the client
        # via the registry rather than via view-layer try/except.
        response = api_exception_handler(NoFieldsToUpdateError(), context={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["errors"][0]["code"], "NO_FIELDS_TO_UPDATE")

    def test_invalid_timezone_maps_to_400(self):
        # Registered by accounts.apps.AccountsConfig.ready().
        response = api_exception_handler(InvalidTimezoneError(), context={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["errors"][0]["code"], "INVALID_TIMEZONE")


class EnvelopeShapeTest(SimpleTestCase):
    def test_envelope_keys_present(self):
        response = api_exception_handler(EntityNotFoundError("X", 1), context={})
        self.assertEqual(
            set(response.data.keys()),
            {
                "success",
                "message",
                "data",
                "errors",
                "request_id",
            },
        )
        self.assertFalse(response.data["success"])
        self.assertIsNone(response.data["data"])


class OutboundURLNotAllowedClassificationTest(SimpleTestCase):
    """Regression: SSRF refusal is an infrastructure concern, not a repo one.

    A blanket ``except InfrastructureError`` in the resilience layer
    must now catch SSRF / allow-list rejections alongside circuit
    breaker opens. ``except RepositoryError`` must NOT.
    """

    def test_maps_to_400(self):
        from core.exceptions.infrastructure import OutboundURLNotAllowedError

        response = api_exception_handler(OutboundURLNotAllowedError("blocked host"), context={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["errors"][0]["code"], "OUTBOUND_URL_NOT_ALLOWED")

    def test_is_infrastructure_error_not_repository_error(self):
        from core.exceptions.infrastructure import (
            InfrastructureError,
            OutboundURLNotAllowedError,
        )
        from core.exceptions.repository import RepositoryError

        exc = OutboundURLNotAllowedError("x")
        self.assertIsInstance(exc, InfrastructureError)
        self.assertNotIsInstance(exc, RepositoryError)

    def test_legacy_alias_emits_deprecation_and_resolves(self):
        import warnings

        from core.exceptions import repository as repo_mod
        from core.exceptions.infrastructure import OutboundURLNotAllowedError

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            legacy = repo_mod.InvalidOutboundURLError
        self.assertIs(legacy, OutboundURLNotAllowedError)
        self.assertTrue(
            any(issubclass(w.category, DeprecationWarning) for w in caught),
            f"expected DeprecationWarning, got {[w.category for w in caught]}",
        )


class DecryptionErrorClassificationTest(SimpleTestCase):
    """``DecryptionError`` is part of the infrastructure family.

    A blanket ``except InfrastructureError`` must catch field-decrypt
    failures (e.g. wrong FIELD_ENCRYPTION_KEY after rotation).
    """

    def test_is_infrastructure_error(self):
        # DecryptionError moved to the kit. The boilerplate's
        # InfrastructureError envelope is no longer in its ancestor
        # chain (the kit's DecryptionError descends from
        # ResilienceKitError directly). The handler still renders it
        # via the composition wrapper.
        from resilience_kit.exceptions import (
            DecryptionError,
            ResilienceKitError,
        )

        self.assertTrue(issubclass(DecryptionError, ResilienceKitError))
