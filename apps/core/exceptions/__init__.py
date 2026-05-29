from core.base.exception import BaseCustomError
from core.exceptions.api import APIError
from core.exceptions.auth import (
    APIKeyRevokedError,
    AuthenticationFailedError,
    PermissionDeniedError,
    TokenExpiredError,
    TokenInvalidError,
    TokenRevokedError,
)
from core.exceptions.handler import api_exception_handler, register_exception_mapping
from core.exceptions.infrastructure import (
    ExternalServiceError,
    ExternalTimeoutError,
    InfrastructureError,
    PartnerPushError,
    S3Exception,
    ServiceUnavailableError,
    SESException,
    TransientError,
)
from core.exceptions.rate_limit import RateLimitError
from core.exceptions.repository import EntityNotFoundError, InactiveParentError, RepositoryError
from core.exceptions.utils import (
    exception_response_payload,
    exception_wire_status,
    normalize_outbound_exception,
)
from core.exceptions.validation import ValidationError

__all__ = [
    "APIError",
    "APIKeyRevokedError",
    "AuthenticationFailedError",
    "BaseCustomError",
    "EntityNotFoundError",
    "ExternalServiceError",
    "ExternalTimeoutError",
    "InactiveParentError",
    "InfrastructureError",
    "PartnerPushError",
    "PermissionDeniedError",
    "RateLimitError",
    "RepositoryError",
    "S3Exception",
    "SESException",
    "ServiceUnavailableError",
    "TokenExpiredError",
    "TokenInvalidError",
    "TokenRevokedError",
    "TransientError",
    "ValidationError",
    "api_exception_handler",
    "exception_response_payload",
    "exception_wire_status",
    "normalize_outbound_exception",
    "register_exception_mapping",
]
