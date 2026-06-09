"""Tenacity-based retry decorator using per-service config from the registry.

Provides automatic retry with exponential backoff for transient failures.
Config is read from ``RESILIENCE_DEFAULTS`` in settings, merged with
per-service overrides registered via ``registry.register_service()``.

Usage as a decorator::

    from core.resilience.retry import retry_on_failure

    @retry_on_failure("payment_gateway")
    def charge_card(card_id, amount):
        return gateway_client.charge(card_id, amount)

Usage with custom config (via registry)::

    from core.resilience.registry import registry

    # In AppConfig.ready() or module level
    registry.register_service("payment_gateway", {
        "retry": {
            "max_attempts": 5,
            "wait_min": 2,
            "wait_max": 30,
        },
    })

    # Then use the decorator — it picks up the overrides
    @retry_on_failure("payment_gateway")
    def charge_card(card_id, amount):
        ...

Combined with circuit breaker (prefer ``@resilient`` shorthand)::

    from core.resilience.decorators import resilient

    @resilient("payment_gateway")  # circuit breaker (outer) + retry (inner)
    def charge_card(card_id, amount):
        ...

Default config (from ``RESILIENCE_DEFAULTS``)::

    {
        "max_attempts": 3,
        "wait_min": 1,       # seconds
        "wait_max": 10,      # seconds
        "retry_on": (TransientError, ExternalTimeoutError),
    }

Only exceptions listed in ``retry_on`` trigger a retry. All others
propagate immediately. After exhausting ``max_attempts``, the last
exception is re-raised (``reraise=True``).
"""

import functools
import threading
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

# Cache built decorators per service to preserve Tenacity's internal
# backoff state across invocations (ISSUE-045). Locked via
# double-checked locking — matches the engine-cache pattern and the
# thread-safety contract in docs/thread-safety.md.
_retry_cache: dict[str, Any] = {}
_retry_cache_lock = threading.Lock()


def retry_on_failure(service_name: str):
    """Decorator that wraps a function with tenacity retry for the named service.

    Args:
        service_name: Identifier matching a key in the resilience registry
            (e.g. ``"s3"``, ``"payment_gateway"``).

    Returns:
        A decorator that adds retry behavior to the wrapped function.

    Example::

        @retry_on_failure("s3")
        def upload_file(bucket, key, data):
            s3_client.put_object(Bucket=bucket, Key=key, Body=data)
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Fast path: cached decorator (preserves backoff state).
            cached = _retry_cache.get(service_name)
            if cached is not None:
                return cached(func)(*args, **kwargs)

            from core.exceptions.infrastructure import ServiceUnavailableError
            from core.resilience.registry import registry

            config = registry.get_config(service_name)["retry"]
            exception_classes = config["retry_on"]

            # Exclude ServiceUnavailableError so retry doesn't defeat an
            # open circuit breaker when used inside @resilient (ISSUE-044).
            exception_classes = tuple(
                cls for cls in exception_classes if not issubclass(cls, ServiceUnavailableError)
            )
            if not exception_classes:
                return func(*args, **kwargs)

            # Slow path: build under lock with double-checked locking.
            with _retry_cache_lock:
                cached = _retry_cache.get(service_name)
                if cached is None:
                    cached = retry(
                        stop=stop_after_attempt(config["max_attempts"]),
                        wait=wait_exponential(
                            min=config["wait_min"],
                            max=config["wait_max"],
                        ),
                        retry=retry_if_exception_type(exception_classes),
                        reraise=True,
                    )
                    _retry_cache[service_name] = cached
            retry_decorator = cached
            return retry_decorator(func)(*args, **kwargs)

        return wrapper

    return decorator
