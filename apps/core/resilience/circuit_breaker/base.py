"""Abstract base classes for the circuit breaker pattern.

Defines the interface that all circuit breaker implementations must follow.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""

    failure_threshold: int = 5
    """Number of consecutive failures before opening circuit."""

    success_threshold: int = 2
    """Number of successes in half-open state to close circuit."""

    recovery_timeout: float = 30.0
    """Seconds to wait in open state before trying half-open."""

    excluded_exceptions: tuple[type[Exception], ...] = ()
    """Exceptions that should not trigger the circuit breaker."""


class BaseCircuitBreaker(ABC):
    """Abstract circuit breaker interface.

    All implementations (pybreaker, Valkey) must implement this interface
    so the rest of the system can work with any backend transparently.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name identifying this breaker."""

    @property
    @abstractmethod
    def time_until_retry(self) -> float:
        """Seconds until circuit will transition from OPEN to HALF_OPEN."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if circuit allows requests (not in OPEN state)."""

    @abstractmethod
    def record_success(self) -> None:
        """Record a successful call."""

    @abstractmethod
    def record_failure(self, exc: Exception | None = None) -> None:
        """Record a failed call."""

    @abstractmethod
    def reset(self) -> None:
        """Reset circuit to closed state."""

    @abstractmethod
    def get_stats(self) -> dict[str, Any]:
        """Get circuit breaker statistics for monitoring."""

    def call(self, func, *args, **kwargs):
        """Execute func through the circuit breaker.

        Checks availability, calls the function, records success/failure.
        Raises ServiceUnavailableError if circuit is open.
        """
        from core.exceptions.infrastructure import ServiceUnavailableError

        if not self.is_available():
            raise ServiceUnavailableError(self.name)

        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as exc:
            self.record_failure(exc)
            raise


class BaseCircuitBreakerRegistry(ABC):
    """Abstract registry for managing circuit breakers per service."""

    @abstractmethod
    def get_or_create(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ) -> BaseCircuitBreaker:
        """Get existing or create new circuit breaker."""

    @abstractmethod
    def remove(self, name: str) -> None:
        """Remove a circuit breaker."""

    @abstractmethod
    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """Get stats for all circuit breakers."""

    @abstractmethod
    def reset_all(self) -> None:
        """Reset all circuit breakers."""

    @abstractmethod
    def clear(self) -> None:
        """Remove all circuit breakers."""
