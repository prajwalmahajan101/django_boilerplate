"""Internal system and infrastructure exceptions.

These exceptions cover failures originating outside the application
boundary: external HTTP services, S3, SES, partner APIs, the circuit
breaker layer, and any other module-level infrastructure that can fail
independently of business logic.

See ``docs/exceptions.md`` for the full hierarchy and status-code mapping.
"""

from __future__ import annotations

from typing import Any

from core.base.exception import BaseCustomError


class InfrastructureError(BaseCustomError):
    """Base error for internal system / infrastructure failures.

    Raised when: a non-domain subsystem (caches, encryption, queues,
        registries, credential stores) fails in a way that is not the
        caller's fault and is not an external network call.
    Maps to: HTTP 500 by default; subclasses register more specific codes.
    Error code: ``INFRASTRUCTURE`` (auto-derived).
    Typical caller: ``apps/core/`` utilities and resilience primitives.
    """

    default_message = "An internal system error occurred."
    error_code = "INFRASTRUCTURE_ERROR"


class ServiceUnavailableError(InfrastructureError):
    """Raised when a service's circuit breaker is open.

    Raised when: an external dependency's circuit breaker is in the OPEN
        state, so the call is short-circuited without dialing the wire.
        Carries ``service_name`` so clients (and dashboards) can identify
        which dependency is being protected.
    Maps to: HTTP 503 (registered in ``handler.py``).
    Error code: ``SERVICE_UNAVAILABLE``.
    Typical caller: ``@resilient`` decorator and circuit-breaker
        implementations in ``apps/core/resilience/circuit_breaker/``.
    """

    default_message = "Service is currently unavailable."
    error_code = "SERVICE_UNAVAILABLE"

    def __init__(
        self,
        service_name: str,
        message: str | None = None,
        *,
        status_code: int | None = None,
    ):
        self.service_name = service_name
        super().__init__(
            message or f"Service '{service_name}' is currently unavailable (circuit breaker open).",
            status_code=status_code,
        )

    def get_details(self) -> dict[str, Any]:
        return {"service_name": self.service_name}


class ExternalServiceError(InfrastructureError):
    """Base error for all external-service failures. Retryable by default.

    Raised when: an outbound call (HTTP, SDK, SMTP, etc.) fails for any
        reason that isn't already covered by a more specific subclass.
        Subclasses encode known failure shapes (timeout, S3, SES, partner
        push) so the resilience layer and tests can match them precisely.
    Maps to: HTTP 502 (registered in ``handler.py`` as the catch-all
        external mapping; must remain LAST in the registration list so
        more specific subclass mappings are evaluated first).
    Error code: ``EXTERNAL_SERVICE``.
    Typical caller: any ``@resilient(...)``-wrapped function.
    """

    default_message = "An external service error occurred."
    error_code = "EXTERNAL_SERVICE_ERROR"


class TransientError(ExternalServiceError):
    """Temporary external failure expected to resolve on retry.

    Raised when: a remote call returned an explicitly retryable signal
        (HTTP 429, transient 5xx, AWS throttling code). The retry
        decorator inspects this class to decide whether to attempt again.
    Maps to: HTTP 502 (inherits ``ExternalServiceError``).
    Error code: ``TRANSIENT``.
    Typical caller: SES retry path; other AWS clients with throttling.
    """

    default_message = "A temporary failure occurred. Please retry."
    error_code = "TRANSIENT_ERROR"


class ExternalTimeoutError(ExternalServiceError):
    """External call exceeded its timeout threshold.

    Raised when: an outbound HTTP / network call did not complete within
        the configured timeout. Distinguished from generic 5xx so the
        resilience layer can apply timeout-specific backoff.
    Maps to: HTTP 502 (registered in ``handler.py``).
    Error code: ``EXTERNAL_TIMEOUT``.
    Typical caller: ``core.utils.http_client`` and any ``@resilient``
        function whose underlying client raises a timeout.
    """

    default_message = "External service call timed out."
    error_code = "EXTERNAL_TIMEOUT"


class S3Exception(ExternalServiceError):
    """Raised when an S3 operation fails.

    Raised when: any boto3 S3 call (upload, download, head, presign,
        delete) raises ``ClientError`` or its URI/parameter validation
        fails. The S3 wrapper translates underlying ``boto3`` /
        ``ValueError`` exceptions into this typed form.
    Maps to: HTTP 502 (registered in ``handler.py``).
    Error code: ``S3``.
    Typical caller: ``apps/core/utils/s3.py`` and ``AssetService``.
    """

    default_message = "An S3 operation failed."
    error_code = "S3_ERROR"


class S3NotFoundError(S3Exception):
    """Raised when an S3 HeadObject/GetObject returns 404 (object absent).

    Raised when: a boto3 S3 call returns a ``404`` / ``NoSuchKey`` /
        ``NotFound`` ``ClientError`` — an expected condition (e.g. a
        cache-miss existence check), not an infrastructure failure.
    Maps to: HTTP 502 (inherited from ``S3Exception`` via ``isinstance``).
    Excluded from the ``s3`` circuit breaker (see ``apps/core/apps.py``) so
        cache-miss checks do not trip it; still an ``S3Exception`` so existing
        ``except S3Exception`` handlers keep working.
    Error code: ``S3_NOT_FOUND``.
    """

    default_message = "S3 object not found."
    error_code = "S3_NOT_FOUND_ERROR"


class SESException(ExternalServiceError):
    """Raised when an SES email operation fails.

    Raised when: a non-retryable failure surfaces from the SES client
        (invalid sender, sandbox restriction, hard-bounce config issue).
        Retryable failures surface as ``TransientError`` instead.
    Maps to: HTTP 502 (registered in ``handler.py``).
    Error code: ``SES``.
    Typical caller: ``apps/core/utils/ses.py`` and Celery email tasks.
    """

    default_message = "An SES email operation failed."
    error_code = "SES_ERROR"


class PartnerPushError(ExternalServiceError):
    """Raised when pushing lead data to a partner API fails.

    Raised when: the partner's push-lead endpoint returns a non-2xx
        status, an unparseable body, or fails connectivity. Wraps the
        downstream HTTP error into the standard envelope so callers
        (admin UI, retry workers) can branch on a typed exception.
    Maps to: HTTP 502 (inherits ``ExternalServiceError``).
    Error code: ``PARTNER_PUSH``.
    """

    default_message = "Failed to push lead to partner."
    error_code = "PARTNER_PUSH_ERROR"
