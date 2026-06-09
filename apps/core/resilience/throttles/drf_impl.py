"""DRF-based throttle fallback classes.

Simple wrappers around DRF's SimpleRateThrottle that read rates from
django_settings.RATE_LIMIT_CONFIG. Used when Valkey is unavailable — all rate limiting
goes through Django's cache framework (which the cache provider handles).

These classes are API-compatible with the Valkey throttle classes
so they can be swapped transparently via the provider.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.resilience.cache.provider import get_cache
from core.resilience.throttles.base import (
    get_user_or_ip_ident,
    get_user_tier,
    log_throttle_event,
)
from django.conf import settings as django_settings
from rest_framework.throttling import SimpleRateThrottle

if TYPE_CHECKING:
    from django.http import HttpRequest
    from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class _CacheAdapter:
    """Bridges BaseCacheBackend to Django cache API for SimpleRateThrottle."""

    def __init__(self, alias: str = "rate_limit"):
        self._alias = alias
        self._backend = None

    def _get_backend(self):
        if self._backend is None:
            self._backend = get_cache(self._alias)
        return self._backend

    def get(self, key, default=None):
        result = self._get_backend().get(key)
        return result if result is not None else default

    def set(self, key, value, timeout=None):
        self._get_backend().set(key, value, timeout=timeout)

    def delete(self, key):
        self._get_backend().delete(key)


class DRFBaseThrottle(SimpleRateThrottle):
    """Base DRF throttle that uses the cache provider instead of Django caches directly."""

    cache_format = "throttle_%(scope)s_%(ident)s"

    def __init__(self) -> None:
        self.cache = _CacheAdapter("rate_limit")
        self.fail_open = django_settings.RATE_LIMIT_CONFIG.get("FAIL_OPEN", True)

        if not getattr(self, "rate", None):
            self.rate = self.get_rate()
        if self.rate is not None:
            self.num_requests, self.duration = self.parse_rate(self.rate)
        else:
            self.num_requests = None
            self.duration = None

    def _get_user_or_ip_ident(self, request: HttpRequest) -> str:
        return get_user_or_ip_ident(request, self.get_ident)

    def get_cache_key(self, request: HttpRequest, view: APIView) -> str | None:
        return self.cache_format % {
            "scope": self.scope,
            "ident": self._get_user_or_ip_ident(request),
        }

    def allow_request(self, request: HttpRequest, view: APIView) -> bool:
        if self.rate is None:
            return True

        try:
            result = super().allow_request(request, view)

            # Set rate limit headers on request for middleware
            if hasattr(self, "num_requests") and self.num_requests:
                history_len = len(self.history) if hasattr(self, "history") else 0
                request._throttle_limit = self.num_requests
                request._throttle_remaining = max(0, self.num_requests - history_len)
                if hasattr(self, "now") and hasattr(self, "duration"):
                    request._throttle_reset = int(self.now + self.duration)

            if not result:
                log_throttle_event(
                    request,
                    view,
                    scope=getattr(self, "scope", "unknown"),
                    rate=self.rate,
                    history_length=len(self.history) if hasattr(self, "history") else 0,
                )

            return result

        except Exception as e:
            logger.warning(
                "DRF rate limit check failed: %s. fail_open=%s",
                str(e),
                self.fail_open,
            )
            return self.fail_open


class DRFUserTierThrottle(DRFBaseThrottle):
    """DRF fallback: user tier-based throttling."""

    scope = "user_tier"
    _current_tier: str = "anon"

    def get_rate(self) -> str:
        user_rates = django_settings.RATE_LIMIT_CONFIG.get("USER_RATES", {})
        return user_rates.get(self._current_tier, "100/minute")

    def allow_request(self, request: HttpRequest, view: APIView) -> bool:
        self._current_tier = get_user_tier(request)
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)


class DRFBurstThrottle(DRFBaseThrottle):
    """DRF fallback: burst protection."""

    scope = "burst"

    def get_rate(self) -> str:
        return django_settings.RATE_LIMIT_CONFIG.get("BURST_RATE", "10/second")


class DRFGlobalThrottle(DRFBaseThrottle):
    """DRF fallback: global rate limiting."""

    scope = "global"

    def get_rate(self) -> str:
        return django_settings.RATE_LIMIT_CONFIG.get("GLOBAL_RATE", "10000/minute")

    def get_cache_key(self, request: HttpRequest, view: APIView) -> str:
        return self.cache_format % {"scope": self.scope, "ident": "global"}


class DRFEndpointThrottle(DRFBaseThrottle):
    """DRF fallback: per-endpoint throttling."""

    scope_attr = "throttle_scope"

    def get_rate(self) -> str | None:
        if not self.scope:
            return None
        endpoint_rates = django_settings.RATE_LIMIT_CONFIG.get("ENDPOINT_RATES", {})
        return endpoint_rates.get(self.scope)

    def allow_request(self, request: HttpRequest, view: APIView) -> bool:
        self.scope = getattr(view, self.scope_attr, None)
        if not self.scope:
            return True
        self.rate = self.get_rate()
        if not self.rate:
            return True
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)

    def get_cache_key(self, request: HttpRequest, view: APIView) -> str | None:
        if not self.scope:
            return None
        ident = f"{self.scope}_{self._get_user_or_ip_ident(request)}"
        return self.cache_format % {"scope": "endpoint", "ident": ident}
