"""Circuit breaker module with pluggable backends.

Default: Valkey (distributed, shared across workers).
Fallback: pybreaker (in-memory, per-process).

Usage::

    from core.resilience.circuit_breaker import get_registry, CircuitBreakerConfig

    # Get the singleton registry (Valkey or pybreaker)
    registry = get_registry()

    # Get or create a breaker for a service
    breaker = registry.get_or_create("payment_gateway")

    # Use manually
    if not breaker.is_available():
        raise ServiceUnavailableError("payment_gateway")
    try:
        result = call_service()
        breaker.record_success()
    except Exception as e:
        breaker.record_failure(e)
        raise

    # Or use the .call() convenience method
    result = breaker.call(call_service, arg1, arg2)
"""

from core.resilience.circuit_breaker.base import (
    BaseCircuitBreaker,
    BaseCircuitBreakerRegistry,
    CircuitBreakerConfig,
    CircuitState,
)
from core.resilience.circuit_breaker.provider import get_registry, reset_registry

__all__ = [
    "BaseCircuitBreaker",
    "BaseCircuitBreakerRegistry",
    "CircuitBreakerConfig",
    "CircuitState",
    "get_registry",
    "reset_registry",
]
