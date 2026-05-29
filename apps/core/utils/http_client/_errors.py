"""Response shape + error re-exports for the outbound HTTP client.

The typed exception hierarchy lives in
:mod:`core.exceptions.infrastructure`; this module re-exports the ones
the client raises so import sites can pull both the response dataclass
and the matching exception types from one place::

    from core.utils.http_client import HttpResponse, TransientError
"""

from __future__ import annotations

from dataclasses import dataclass

from core.exceptions.infrastructure import (
    ExternalTimeoutError,
    OutboundURLNotAllowedError,
    TransientError,
)


@dataclass(frozen=True)
class HttpResponse:
    """Structured response from an HTTP call.

    ``body`` is the parsed JSON / text by default, or the raw response
    ``bytes`` when the call was made with ``raw_bytes=True`` — used for
    binary downloads (e.g. documents) where JSON/text parsing would
    corrupt the payload.

    ``request`` carries the request side of the round-trip
    (``method``, ``url``, ``headers``, ``body``) so audit decorators
    such as :func:`core.api_log.log_outbound` can persist a complete
    record without re-introspecting the caller's args. Optional for
    backward compatibility — callers that don't use ``api_log`` can
    leave it ``None``.
    """

    status_code: int
    body: dict | str | bytes | None
    headers: dict
    request: dict | None = None


__all__ = [
    "ExternalTimeoutError",
    "HttpResponse",
    "OutboundURLNotAllowedError",
    "TransientError",
]
