"""Pydantic schema for the boilerplate response envelope.

Distinct from :class:`SuccessResponse` / :class:`ErrorResponse` /
:class:`PaginatedResponse` in this package — those are DRF
``Response`` *builders* that emit the envelope shape at view boundary.
This module ships the *contract* the envelope obeys, in pydantic form,
so that:

1. The kit's
   :func:`resilience_kit.adapters._envelope.from_exception` can be
   pointed at it and produce envelope-shaped bodies for any
   :class:`ResilienceKitError` (closes M7 B2 — used by
   ``api_exception_handler`` for raw kit exceptions).

2. :func:`resilience_kit.testing.verify_envelope_contract` can validate
   that every kit exception still renders cleanly through our handler
   (closes M7 §3.6 — pinned by ``tests/test_envelope_contract.py``).

Field set mirrors the response builders exactly. If those builders
ever grow a new field, mirror it here in the same commit.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ResponseEnvelope(BaseModel):
    """The five-field response envelope every API endpoint returns."""

    success: bool
    message: str
    data: Any | None = None
    errors: list[dict[str, Any]] | None = None
    request_id: str | None = None


__all__ = ["ResponseEnvelope"]
