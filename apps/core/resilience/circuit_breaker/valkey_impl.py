"""Valkey-backed circuit breaker for cross-process state sharing.

In a multi-worker deployment (gunicorn prefork), per-process circuit breakers
maintain independent state. This module provides a Valkey-backed implementation
that shares circuit breaker state across all workers via atomic Lua scripts.

Fail-open: If Valkey is unavailable, each ValkeyCircuitBreaker falls back to
a PyBreakerCircuitBreaker. If Valkey fails at registry construction time,
the entire ValkeyRegistry degrades to a PyBreakerRegistry.

Key schema:
    Valkey hash ``cb:{name}`` with fields:
        state, failure_count, success_count, last_failure
    TTL: ``recovery_timeout * 10`` (refreshed on every write)

All state mutations use a single Lua script (one EVALSHA round-trip) for atomicity.
"""

from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Any

from valkey.exceptions import NoScriptError

from core.resilience.circuit_breaker.base import (
    BaseCircuitBreaker,
    BaseCircuitBreakerRegistry,
    CircuitBreakerConfig,
)
from core.resilience.circuit_breaker.pybreaker_impl import (
    PyBreakerCircuitBreaker,
    PyBreakerRegistry,
)
from core.utils.valkey import get_valkey_client

logger = logging.getLogger(__name__)

# Single Lua script handling all circuit breaker operations.
# KEYS[1] = hash key (e.g. "cb:payment_gateway")
# ARGV[1] = action: "is_available", "record_success", "record_failure", "reset", "get_stats"
# ARGV[2] = failure_threshold
# ARGV[3] = success_threshold
# ARGV[4] = recovery_timeout (seconds)
# ARGV[5] = current time (epoch float as string)
CIRCUIT_BREAKER_LUA_SCRIPT = """
local key = KEYS[1]
local action = ARGV[1]
local failure_threshold = tonumber(ARGV[2])
local success_threshold = tonumber(ARGV[3])
local recovery_timeout = tonumber(ARGV[4])
local now = tonumber(ARGV[5])
local ttl = math.ceil(recovery_timeout * 10)

local function read_state()
    local vals = redis.call('HMGET', key, 'state', 'failure_count', 'success_count', 'last_failure')
    local state = vals[1] or 'closed'
    local fc = tonumber(vals[2]) or 0
    local sc = tonumber(vals[3]) or 0
    local lf = tonumber(vals[4]) or 0
    return state, fc, sc, lf
end

local function write_state(state, fc, sc, lf)
    redis.call('HMSET', key, 'state', state, 'failure_count', fc, 'success_count', sc, 'last_failure', lf)
    redis.call('EXPIRE', key, ttl)
end

local state, fc, sc, lf = read_state()

if state == 'open' and (now - lf) >= recovery_timeout then
    state = 'half_open'
    sc = 0
    write_state(state, fc, sc, lf)
end

if action == 'is_available' then
    if state == 'open' then
        local remaining = recovery_timeout - (now - lf)
        if remaining < 0 then remaining = 0 end
        return {0, state, tostring(remaining)}
    end
    return {1, state, '0'}

elseif action == 'record_success' then
    if state == 'half_open' then
        sc = sc + 1
        if sc >= success_threshold then
            state = 'closed'
            fc = 0
        end
    elseif state == 'closed' then
        fc = 0
    end
    write_state(state, fc, sc, lf)
    return {1, state, '0'}

elseif action == 'record_failure' then
    fc = fc + 1
    lf = now
    if state == 'half_open' then
        state = 'open'
    elseif state == 'closed' and fc >= failure_threshold then
        state = 'open'
    end
    write_state(state, fc, sc, lf)
    local remaining = 0
    if state == 'open' then
        remaining = recovery_timeout
    end
    return {1, state, tostring(remaining)}

elseif action == 'reset' then
    redis.call('DEL', key)
    return {1, 'closed', '0'}

elseif action == 'get_stats' then
    return {state, tostring(fc), tostring(sc), tostring(lf)}
end

return {0, 'error', '0'}
"""


class ValkeyCircuitBreaker(BaseCircuitBreaker):
    """Valkey-backed circuit breaker with fail-open to pybreaker fallback.

    Every method attempts the Valkey Lua script first. If Valkey is
    unreachable, it transparently falls back to a PyBreakerCircuitBreaker
    so the application continues with per-process state rather than failing.
    """

    def __init__(
        self,
        breaker_name: str,
        config: CircuitBreakerConfig,
        valkey_client: Any,
        lua_sha: str,
        key_prefix: str = "cb",
    ) -> None:
        self._name = breaker_name
        self._config = config
        self._valkey = valkey_client
        self._lua_sha = lua_sha
        self._key = f"{key_prefix}:{breaker_name}"
        self._fallback = PyBreakerCircuitBreaker(breaker_name=breaker_name, config=config)
        self._using_fallback = False
        self._fallback_lock = Lock()

    @property
    def name(self) -> str:
        return self._name

    def _call_lua(self, action: str) -> list:
        """Execute the Lua script. On failure, switch to fallback."""
        try:
            result = self._valkey.evalsha(
                self._lua_sha,
                1,
                self._key,
                action,
                self._config.failure_threshold,
                self._config.success_threshold,
                self._config.recovery_timeout,
                time.time(),
            )
            with self._fallback_lock:
                self._using_fallback = False
            return result
        except NoScriptError:
            # Script evicted — reload and retry once.
            self._lua_sha = self._valkey.script_load(CIRCUIT_BREAKER_LUA_SCRIPT)
            result = self._valkey.evalsha(
                self._lua_sha,
                1,
                self._key,
                action,
                self._config.failure_threshold,
                self._config.success_threshold,
                self._config.recovery_timeout,
                time.time(),
            )
            with self._fallback_lock:
                self._using_fallback = False
            return result
        except Exception as e:
            with self._fallback_lock:
                if not self._using_fallback:
                    logger.warning(
                        "Valkey circuit breaker unavailable, falling back to pybreaker",
                        extra={"breaker": self._name, "error": str(e)},
                    )
                    self._using_fallback = True
            raise

    @property
    def time_until_retry(self) -> float:
        try:
            result = self._call_lua("is_available")
            return float(result[2])
        except Exception:
            return self._fallback.time_until_retry

    def is_available(self) -> bool:
        try:
            result = self._call_lua("is_available")
            return bool(int(result[0]))
        except Exception:
            return self._fallback.is_available()

    def record_success(self) -> None:
        try:
            self._call_lua("record_success")
        except Exception:
            self._fallback.record_success()

    def record_failure(self, exc: Exception | None = None) -> None:
        if exc is not None and isinstance(exc, self._config.excluded_exceptions):
            return
        try:
            self._call_lua("record_failure")
        except Exception:
            self._fallback.record_failure(exc)

    def reset(self) -> None:
        try:
            self._call_lua("reset")
        except Exception:
            self._fallback.reset()

    def get_stats(self) -> dict[str, Any]:
        try:
            result = self._call_lua("get_stats")
            state_val = result[0]
            if isinstance(state_val, bytes):
                state_val = state_val.decode()
            return {
                "name": self._name,
                "state": state_val,
                "failure_count": int(result[1]),
                "success_count": int(result[2]),
                "time_until_retry": self.time_until_retry,
                "backend": "valkey",
            }
        except Exception:
            stats = self._fallback.get_stats()
            stats["backend"] = "pybreaker-fallback"
            return stats


class ValkeyRegistry(BaseCircuitBreakerRegistry):
    """Registry for Valkey-backed circuit breakers.

    If Valkey is unavailable at construction time, degrades entirely
    to PyBreakerRegistry.
    """

    def __init__(
        self,
        default_config: CircuitBreakerConfig | None = None,
        valkey_alias: str = "rate_limit",
        key_prefix: str = "cb",
    ) -> None:
        self._default_config = default_config or CircuitBreakerConfig()
        self._key_prefix = key_prefix
        self._breakers: dict[str, ValkeyCircuitBreaker] = {}
        self._lock = Lock()
        self._valkey_client = None
        self._lua_sha: str | None = None
        self._degraded_registry: PyBreakerRegistry | None = None

        try:
            self._valkey_client = get_valkey_client(valkey_alias)
            self._lua_sha = self._valkey_client.script_load(CIRCUIT_BREAKER_LUA_SCRIPT)
            logger.info(
                "Valkey circuit breaker registry initialized (key_prefix=%s)", key_prefix
            )
        except Exception as e:
            logger.warning(
                "Failed to initialize Valkey circuit breaker registry, "
                "falling back to pybreaker: %s",
                e,
            )
            self._degraded_registry = PyBreakerRegistry(
                default_config=self._default_config
            )

    @property
    def _is_degraded(self) -> bool:
        return self._degraded_registry is not None

    def get_or_create(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ) -> ValkeyCircuitBreaker | PyBreakerCircuitBreaker:
        if self._is_degraded:
            return self._degraded_registry.get_or_create(name, config)

        breaker = self._breakers.get(name)
        if breaker is not None:
            return breaker

        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = ValkeyCircuitBreaker(
                    breaker_name=name,
                    config=config or self._default_config,
                    valkey_client=self._valkey_client,
                    lua_sha=self._lua_sha,
                    key_prefix=self._key_prefix,
                )
            return self._breakers[name]

    def remove(self, name: str) -> None:
        if self._is_degraded:
            self._degraded_registry.remove(name)
            return

        with self._lock:
            self._breakers.pop(name, None)
        try:
            self._valkey_client.delete(f"{self._key_prefix}:{name}")
        except Exception:
            pass

    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        if self._is_degraded:
            return self._degraded_registry.get_all_stats()

        with self._lock:
            return {name: cb.get_stats() for name, cb in self._breakers.items()}

    def reset_all(self) -> None:
        if self._is_degraded:
            self._degraded_registry.reset_all()
            return

        with self._lock:
            for breaker in self._breakers.values():
                breaker.reset()

    def clear(self) -> None:
        if self._is_degraded:
            self._degraded_registry.clear()
            return

        with self._lock:
            for name in self._breakers:
                try:
                    self._valkey_client.delete(f"{self._key_prefix}:{name}")
                except Exception:
                    pass
            self._breakers.clear()
