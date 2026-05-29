"""Resilience decorators combining circuit breaker and retry."""

import functools

from core.resilience.retry import retry_on_failure


def circuit_breaker(service_name: str):
    """Decorator that wraps a function with a circuit breaker.

    Uses the provider-backed registry (Valkey default, pybreaker fallback).
    Raises ServiceUnavailableError if the circuit is open.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            from core.resilience.registry import registry

            breaker = registry.get_breaker(service_name)
            return breaker.call(func, *args, **kwargs)

        return wrapper

    return decorator


def resilient(service_name: str):
    """Combined decorator: circuit breaker (outer) wrapping retry (inner)."""

    def decorator(func):
        retried = retry_on_failure(service_name)(func)
        protected = circuit_breaker(service_name)(retried)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return protected(*args, **kwargs)

        return wrapper

    return decorator
