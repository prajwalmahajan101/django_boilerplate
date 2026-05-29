"""Shared throttle helpers used by both Valkey and DRF implementations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.utils.log_sanitization import safe_log_dict

if TYPE_CHECKING:
    from django.http import HttpRequest
    from rest_framework.views import APIView

logger = logging.getLogger(__name__)


def get_user_tier(request: HttpRequest) -> str:
    """Determine the user's tier for rate limiting.

    Returns:
        "anon", "user", or "admin"
    """
    if not request.user or not request.user.is_authenticated:
        return "anon"
    if getattr(request.user, "has_superuser_role", False):
        return "admin"
    return "user"


def get_user_or_ip_ident(request: HttpRequest, get_ident_func) -> str:
    """Return user PK if authenticated, otherwise client IP."""
    if request.user and request.user.is_authenticated:
        return str(request.user.pk)
    return get_ident_func(request)


def log_throttle_event(
    request: HttpRequest,
    view: APIView,
    *,
    scope: str,
    rate: str | None,
    history_length: int,
) -> None:
    """Log a throttle event for monitoring."""
    user_id = getattr(request.user, "pk", None) if request.user else None
    logger.warning(
        "Request throttled",
        extra=safe_log_dict(
            scope=scope,
            user_id=user_id,
            path=request.path,
            rate=rate,
            history_length=history_length,
        ),
    )
