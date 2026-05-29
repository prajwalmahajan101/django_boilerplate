"""Data access layer exceptions.

These exceptions cover failures originating in the repository / ORM layer:
missing rows, integrity violations, parent-state preconditions. They are
distinct from ``InfrastructureError`` (external systems) and from DRF
``ValidationError`` (request payload validation).

See ``docs/exceptions.md`` for the full hierarchy and status-code mapping.
"""

from __future__ import annotations

from typing import Any

from core.base.exception import BaseCustomError


class RepositoryError(BaseCustomError):
    """Base error for data access layer failures.

    Raised when: a repository / service-layer operation fails for reasons
        rooted in stored data (missing rows, broken invariants, integrity
        conflicts) rather than external systems or request validation.
    Maps to: HTTP 500 by default (no specific registration); subclasses
        override with their own registrations or use ``status_code=...``.
    Error code: ``REPOSITORY`` (auto-derived).
    Typical caller: any ``BaseService`` subclass.
    """

    default_message = "A data access error occurred."
    error_code = "REPOSITORY_ERROR"


class EntityNotFoundError(RepositoryError):
    """Raised when a requested entity does not exist.

    Raised when: a service-layer ``get_or_fail``-style lookup returns
        nothing — either the row was never created or it was soft-deleted
        and the lookup excluded inactive rows.
    Maps to: HTTP 404 (registered in ``handler.py``).
    Error code: ``ENTITY_NOT_FOUND``.
    Typical caller: ``BaseService.get_by_id_or_fail`` and any service that
        looks up a single row by primary key.
    Details: includes ``entity_name`` and ``entity_id`` in the response
        envelope's ``errors[].details`` for client-side disambiguation.
    """

    default_message = "Entity not found."
    error_code = "ENTITY_NOT_FOUND"

    def __init__(
        self,
        entity_name: str,
        entity_id: int | str,
        *,
        status_code: int | None = None,
    ) -> None:
        self.entity_name = entity_name
        self.entity_id = entity_id
        super().__init__(
            f"{entity_name} with id={entity_id} not found.",
            status_code=status_code,
        )

    def get_details(self) -> dict[str, Any]:
        return {"entity_name": self.entity_name, "entity_id": self.entity_id}


class InactiveParentError(RepositoryError):
    """Raised when activating a resource whose parent is inactive.

    Raised when: a service tries to set ``is_active=True`` on a child row
        whose parent is itself ``is_active=False``. The cascade contract
        forbids reviving children under a dead parent — callers should
        reactivate the parent first.
    Maps to: HTTP 409 (registered in ``handler.py``).
    Error code: ``INACTIVE_PARENT``.
    Typical caller: services that manage parent-child resources with
        cascade semantics (e.g. ``QueryService``, ``RemarkService``).
    """

    default_message = "Cannot activate: parent resource is inactive."
    error_code = "INACTIVE_PARENT"

    def __init__(
        self,
        message: str | None = None,
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message or self.default_message, status_code=status_code)


class InvalidOutboundURLError(RepositoryError):
    """Raised when an outbound URL fails SSRF / allow-list validation.

    Raised when: the SSRF guard in ``apps/core/utils/http_client.py``
        rejects a URL because the scheme is not http(s), the hostname
        is missing, DNS does not resolve (strict mode), the resolved
        address is non-public (RFC1918, loopback, link-local, etc.),
        or the host is not in ``OUTBOUND_URL_ALLOWLIST``.
    Maps to: HTTP 400 (registered in ``handler.py``).
    Error code: ``INVALID_OUTBOUND_URL``.
    Typical caller: ``_assert_url_allowlisted`` and ``_assert_public_url``
        in ``apps/core/utils/http_client.py``.
    """

    default_message = "Outbound URL is not allowed."
    error_code = "INVALID_OUTBOUND_URL"


class InvalidInputError(RepositoryError):
    """Raised when a caller passes structurally invalid input to a core utility.

    Raised when: a shared ``core/utils`` helper (S3 URI parsing, filter
        coercion, length-bounded sanitization) is handed input that
        cannot be processed. Surfaces as 400 instead of a stdlib
        ``ValueError`` so the response envelope is honoured.
    Maps to: HTTP 400 (registered in ``handler.py``).
    Error code: ``INVALID_INPUT``.
    Typical caller: ``apps/core/utils/{data,filters,s3}.py``.
    """

    default_message = "Invalid input."
    error_code = "INVALID_INPUT"
