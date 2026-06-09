"""Valkey-backed throttle classes with atomic Lua scripts.

Primary throttle implementation. Uses Lua scripts for atomic rate limiting
and falls back to non-atomic cache operations when Lua is unavailable.

Cache operations go through the cache provider (core.resilience.cache).
"""

from __future__ import annotations

import logging
import math
import time
from threading import Lock
from typing import TYPE_CHECKING

from core.resilience.cache.provider import get_cache
from core.resilience.throttles import global_lua
from core.resilience.throttles.base import (
    get_user_or_ip_ident,
    get_user_tier,
    log_throttle_event,
)
from core.resilience.throttles.cache_adapter import DjangoCacheAdapter
from core.resilience.throttles.lua_scripts import THROTTLE_LUA_SCRIPT
from core.utils.log_sanitization import safe_log_dict
from core.utils.valkey import get_valkey_client
from django.conf import settings as django_settings
from rest_framework.throttling import SimpleRateThrottle

if TYPE_CHECKING:
    from django.http import HttpRequest
    from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class ValkeyRateThrottle(SimpleRateThrottle):
    """Base throttle using Valkey cache with atomic Lua scripts.

    Falls back to non-atomic cache operations (via cache provider)
    when Lua scripting is unavailable.
    """

    cache_format = "throttle_%(scope)s_%(ident)s"
    timer = time.time

    # Class-level Valkey client cache. DRF instantiates throttles per
    # request, so any instance-level state has request-scoped lifetime.
    # Share the client across all subclasses since they all target the
    # same "rate_limit" alias.
    _shared_valkey_client = None
    _shared_valkey_client_lock = Lock()

    # Once-per-process WARNING when Lua script load fails. DRF instantiates
    # throttles per request, so a noisy log without this guard would log
    # the same failure on every request. ``_lua_failure_warned`` is set
    # only after the first failure logs; the recovery monitor can reset
    # it via ``reset_lua_state()`` once Valkey is reachable again.
    _lua_failure_warned = False
    _lua_warning_lock = Lock()

    def __init__(self) -> None:
        self._init_cache()
        self._init_lua_script()
        self.fail_open = django_settings.RATE_LIMIT_CONFIG.get("FAIL_OPEN", True)
        self.history: list = []

        if not getattr(self, "rate", None):
            self.rate = self.get_rate()
        if self.rate is not None:
            self.num_requests, self.duration = self.parse_rate(self.rate)
        else:
            self.num_requests = None
            self.duration = None

    def _init_cache(self) -> None:
        """Initialize cache via the cache provider."""
        self._cache_backend = get_cache("rate_limit")
        # DRF's SimpleRateThrottle expects self.cache — provide a compatible wrapper
        self.cache = DjangoCacheAdapter(self._cache_backend)
        # Warm the shared Valkey client on first instantiation so every
        # subsequent request reuses the same reference.
        self._get_valkey_client()

    def _get_valkey_client(self):
        cls = ValkeyRateThrottle  # always share across subclasses
        if cls._shared_valkey_client is None:
            with cls._shared_valkey_client_lock:
                if cls._shared_valkey_client is None:
                    try:
                        cls._shared_valkey_client = get_valkey_client("rate_limit")
                    except Exception:
                        return None
        return cls._shared_valkey_client

    def _init_lua_script(self) -> None:
        self._lua_script_sha = None
        try:
            client = self._get_valkey_client()
            self._lua_script_sha = client.script_load(THROTTLE_LUA_SCRIPT)
        except Exception as exc:
            self._warn_lua_load_failed_once(exc)

    @classmethod
    def _warn_lua_load_failed_once(cls, exc: Exception) -> None:
        """Emit a single WARNING the first time Lua load fails per process.

        Without this guard, DRF's per-request throttle instantiation would
        log the same failure on every request. The flag is reset via
        ``reset_lua_state()`` so the recovery monitor (or a readiness
        probe) can re-warn once Valkey recovers and fails again.
        """
        if cls._lua_failure_warned:
            return
        with cls._lua_warning_lock:
            if cls._lua_failure_warned:
                return
            logger.warning(
                "Valkey throttle Lua script load failed; "
                "falling back to non-atomic rate limiting. error=%s",
                str(exc),
                extra={"subsystem": "throttle"},
            )
            cls._lua_failure_warned = True

    @classmethod
    def reset_lua_state(cls) -> None:
        """Clear the once-per-process WARNING gate.

        Called by the recovery monitor after Valkey returns so the next
        failure re-emits the WARNING instead of being swallowed by the
        gate.
        """
        with cls._lua_warning_lock:
            cls._lua_failure_warned = False

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
            self.key = self.get_cache_key(request, view)
            if self.key is None:
                return True

            self.now = self.timer()

            if self._lua_script_sha:
                return self._allow_request_atomic(request, view)

            return self._allow_request_non_atomic(request, view)

        except Exception as e:
            logger.warning(
                "Rate limit check failed: %s. fail_open=%s",
                str(e),
                self.fail_open,
                extra=safe_log_dict(
                    scope=getattr(self, "scope", "unknown"),
                    error=str(e),
                ),
            )
            return self.fail_open

    def _allow_request_atomic(self, request: HttpRequest, view: APIView) -> bool:
        client = self._get_valkey_client()
        result = client.evalsha(
            self._lua_script_sha,
            1,
            self.key,
            self.num_requests,
            self.duration,
            self.now,
        )

        allowed, current_count, ttl = result

        request._throttle_limit = self.num_requests
        request._throttle_remaining = max(0, self.num_requests - current_count)
        request._throttle_reset = int(self.now + (ttl if ttl > 0 else self.duration))

        if not allowed:
            log_throttle_event(
                request,
                view,
                scope=getattr(self, "scope", "unknown"),
                rate=self.rate,
                history_length=current_count,
            )
            self.history = list(range(current_count))
            request._throttle_wait = self.wait()
            request._throttle_remaining = 0
            return self.throttle_failure()

        return True

    def _allow_request_non_atomic(self, request: HttpRequest, view: APIView) -> bool:
        self.history = self.cache.get(self.key, [])

        while self.history and self.history[-1] <= self.now - self.duration:
            self.history.pop()

        request._throttle_limit = self.num_requests
        request._throttle_remaining = max(0, self.num_requests - len(self.history))
        request._throttle_reset = int(self.now + self.duration)

        if len(self.history) >= self.num_requests:
            log_throttle_event(
                request,
                view,
                scope=getattr(self, "scope", "unknown"),
                rate=self.rate,
                history_length=len(self.history),
            )
            request._throttle_wait = self.wait()
            request._throttle_remaining = 0
            return self.throttle_failure()

        return self.throttle_success()

    def throttle_success(self) -> bool:
        try:
            self.history.insert(0, self.now)
            self.cache.set(self.key, self.history, self.duration)
        except Exception as e:
            logger.warning("Failed to record throttle success: %s", str(e))
        return True


class UserTierThrottle(ValkeyRateThrottle):
    """User tier-based throttling with different rates per user type."""

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


class BurstThrottle(ValkeyRateThrottle):
    """Burst protection throttle to prevent rapid-fire requests."""

    scope = "burst"

    def get_rate(self) -> str:
        return django_settings.RATE_LIMIT_CONFIG.get("BURST_RATE", "10/second")


class GlobalThrottle(ValkeyRateThrottle):
    """Global API rate limiting using O(1) sliding window counter.

    The Lua-script SHA cache + load helper for this throttle's atomic
    path lives in ``core.resilience.throttles.global_lua`` — it's
    process-wide state with its own algorithm and was extracted so the
    throttle classes here only contain throttle logic.
    """

    scope = "global"

    def get_rate(self) -> str:
        return django_settings.RATE_LIMIT_CONFIG.get("GLOBAL_RATE", "10000/minute")

    def __init__(self) -> None:
        super().__init__()
        global_lua.ensure_loaded(self._get_valkey_client)

    def get_cache_key(self, request: HttpRequest, view: APIView) -> str:
        return self.cache_format % {"scope": self.scope, "ident": "global"}

    def allow_request(self, request: HttpRequest, view: APIView) -> bool:
        if self.rate is None:
            return True

        try:
            self.key = self.get_cache_key(request, view)
            if self.key is None:
                return True

            self.now = self.timer()

            if global_lua.get_sha():
                return self._allow_request_global_atomic(request, view)
            return self._allow_request_global_fallback(request, view)

        except Exception as e:
            logger.warning(
                "Global throttle check failed: %s. fail_open=%s",
                str(e),
                self.fail_open,
                extra=safe_log_dict(scope=self.scope, error=str(e)),
            )
            return self.fail_open

    def _allow_request_global_atomic(self, request: HttpRequest, view: APIView) -> bool:
        client = self._get_valkey_client()
        sha = global_lua.get_sha()

        try:
            result = client.evalsha(
                sha,
                1,
                self.key,
                self.num_requests,
                self.duration,
                self.now,
            )
        except Exception:
            # NOSCRIPT-style failure: drop the cached SHA and re-load.
            global_lua.reset()
            sha = global_lua.ensure_loaded(self._get_valkey_client)
            if sha:
                result = client.evalsha(
                    sha,
                    1,
                    self.key,
                    self.num_requests,
                    self.duration,
                    self.now,
                )
            else:
                return self._allow_request_global_fallback(request, view)

        allowed, effective_count, ttl = result
        window_start = int(self.now // self.duration) * self.duration

        request._throttle_limit = self.num_requests
        request._throttle_remaining = max(0, self.num_requests - effective_count)
        request._throttle_reset = int(window_start + self.duration)

        if not allowed:
            log_throttle_event(
                request,
                view,
                scope=self.scope,
                rate=self.rate,
                history_length=effective_count,
            )
            self.history = list(range(effective_count))
            request._throttle_wait = self.wait()
            request._throttle_remaining = 0
            return self.throttle_failure()

        return True

    def _allow_request_global_fallback(self, request: HttpRequest, view: APIView) -> bool:
        window_start = int(self.now // self.duration) * self.duration
        window_position = (self.now - window_start) / self.duration

        current_key = f"{self.key}:{int(window_start)}"
        previous_key = f"{self.key}:{int(window_start - self.duration)}"

        client = self._get_valkey_client()
        pipe = client.pipeline()
        pipe.get(current_key)
        pipe.get(previous_key)
        current_count, previous_count = pipe.execute()

        current_count = int(current_count or 0)
        previous_count = int(previous_count or 0)

        effective_count = current_count + previous_count * (1 - window_position)

        request._throttle_limit = self.num_requests
        request._throttle_remaining = max(0, self.num_requests - math.ceil(effective_count))
        request._throttle_reset = int(window_start + self.duration)

        if effective_count >= self.num_requests:
            log_throttle_event(
                request,
                view,
                scope=self.scope,
                rate=self.rate,
                history_length=int(effective_count),
            )
            self.history = list(range(int(effective_count)))
            request._throttle_wait = self.wait()
            request._throttle_remaining = 0
            return self.throttle_failure()

        pipe = client.pipeline()
        pipe.incr(current_key)
        pipe.expire(current_key, self.duration * 2)
        pipe.execute()

        return True


class EndpointThrottle(ValkeyRateThrottle):
    """Per-endpoint throttling based on view configuration."""

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
