"""Account-domain exceptions.

Typed exceptions raised by account models, services, and authentication
helpers. All inherit from ``BaseCustomError`` so the DRF exception handler
wraps them in the standard envelope with a derived ``error_code``.

See ``docs/exceptions.md`` for the full hierarchy and status-code mapping.
"""

from __future__ import annotations

from core.base.exception import BaseCustomError
from core.exceptions.infrastructure import InfrastructureError


class APIKeyGenerationError(InfrastructureError):
    """Raised when a unique API-key prefix cannot be generated after retries.

    Raised when: ``APIKey.create_key`` exhausts its three-attempt retry loop
        because every random prefix collided with an existing row's prefix.
        Astronomically unlikely under healthy entropy — typically a signal
        of entropy starvation, a corrupt unique index, or a test fixture
        that pre-seeds prefixes.
    Maps to: HTTP 500 (registered in ``accounts.apps.AccountsConfig.ready``).
    Error code: ``API_KEY_GENERATION`` (auto-derived from the class name).
    Typical caller: ``apps/accounts/models.py::APIKey.create_key``.
    """

    default_message = "Failed to generate a unique API key prefix after 3 attempts."
    error_code = "API_KEY_GENERATION"


class NoFieldsToUpdateError(BaseCustomError):
    """Raised when a profile-update request has no recognized writable fields.

    Raised when: ``UserService.update_profile`` filters the incoming payload
        against ``UPDATABLE_PROFILE_FIELDS`` and the result is empty.
    Maps to: HTTP 400 (registered in ``accounts.apps.AccountsConfig.ready``).
    Error code: ``NO_FIELDS_TO_UPDATE``.
    Typical caller: ``apps/accounts/services.py::UserService.update_profile``.
    """

    default_message = "No valid fields to update."
    error_code = "NO_FIELDS_TO_UPDATE"


class InvalidTimezoneError(BaseCustomError):
    """Raised when a supplied timezone is not a valid IANA identifier.

    Raised when: ``UserService.update_profile`` validates ``timezone``
        against ``zoneinfo.available_timezones()`` and the value is absent.
    Maps to: HTTP 400 (registered in ``accounts.apps.AccountsConfig.ready``).
    Error code: ``INVALID_TIMEZONE``.
    Typical caller: ``apps/accounts/services.py::UserService.update_profile``.
    """

    default_message = "Invalid timezone. Use a valid IANA timezone identifier."
    error_code = "INVALID_TIMEZONE"
