"""Base exception for all custom application exceptions.

Inherits from :class:`resilience_kit.exceptions.ResilienceKitError` so
every boilerplate domain exception is *also* a kit exception. This is
the M7 bridge — it lets:

* the kit's ``exception_handler.handle`` recognise our exceptions
  (we still wrap them via the composition wrapper in ``handler.py``);
* the kit's ``@retry`` / ``@resilient`` policies match on our subclasses
  of ``TransientError`` / ``ExternalTimeoutError`` without the boilerplate
  having to translate at every raise site;
* downstream services depending on the kit see one exception hierarchy
  instead of two parallel trees.

The single point of bridging keeps domain subclasses (``S3Exception``,
``SESException``, ``PartnerPushError``, ``OutboundURLNotAllowedError``)
unchanged — they still descend through ``BaseCustomError`` and pick up
the kit ancestry for free.
"""

from __future__ import annotations

import re
from typing import Any

from resilience_kit.exceptions import ResilienceKitError

from core.context import get_request_id


def derive_error_code(name: str, *, strip_suffix: bool = True) -> str:
    """Turn a class name into an UPPER_SNAKE_CASE error code.

    ``strip_suffix=True`` (BaseCustomError convention) drops a trailing
    ``Error``/``Exception`` so ``EntityNotFoundError`` → ``ENTITY_NOT_FOUND``.
    ``strip_suffix=False`` (DRF convention) preserves it, since DRF
    classes like ``NotAuthenticated`` don't carry the suffix.
    """
    if strip_suffix:
        name = re.sub(r"(Error|Exception)$", "", name)
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).upper()


class BaseCustomError(ResilienceKitError):
    """Root of all custom application exceptions.

    Every project-specific exception inherits from this class so the DRF
    handler (``core.exceptions.handler.api_exception_handler``) can wrap
    it in the standard ``{"success": False, "errors": [...], ...}``
    envelope without checking against a hard-coded type list.

    Subclass contract:
      * Set ``default_message`` to a human-readable fallback used when
        no explicit ``message`` is passed to ``__init__``.
      * Optionally set ``error_code`` to a machine-readable UPPER_SNAKE_CASE
        string. If omitted, ``_derive_error_code()`` produces one from the
        class name (e.g., ``EntityNotFoundError`` → ``ENTITY_NOT_FOUND``).
      * Override ``get_details()`` to attach structured context to the
        ``errors[].details`` field of the envelope.

    Status code mapping:
      * Default: HTTP 500.
      * Per-instance override: ``raise BaseCustomError("…", status_code=409)``
        for ad-hoc domain rule violations at the service layer.
      * Class-level mapping: ``register_exception_mapping(MyError, 4xx)``
        (preferred for stable, type-driven mappings — see ``handler.py``).

    Request correlation:
      * The current ``request_id`` is captured from
        ``core.utils.logging._request_id_var`` at construction time so the
        envelope can echo it back to the client.

    See ``docs/exceptions.md`` for the full hierarchy, the registration
    contract, and decision guidance on which subclass to use.
    """

    default_message: str = "An unexpected error occurred."
    error_code: str | None = None

    def __init__(self, message: str | None = None, *, status_code: int | None = None):
        self.message = message or self.default_message
        if status_code is not None:
            self.status_code = status_code
        self.request_id: str | None = get_request_id()
        super().__init__(self.message)

    def _derive_error_code(self) -> str:
        """Derive UPPER_SNAKE_CASE code from the class name."""
        return derive_error_code(type(self).__name__, strip_suffix=True)

    def get_error_code(self) -> str:
        """Return the machine-readable error code."""
        return self.error_code or self._derive_error_code()

    def get_details(self) -> dict[str, Any] | None:
        """Return context-specific details for this error."""
        return None

    def to_error_dict(self) -> dict[str, Any]:
        """Build a structured error dict for the response envelope."""
        return {
            "code": self.get_error_code(),
            "message": self.message,
            "field": None,
            "details": self.get_details(),
        }
