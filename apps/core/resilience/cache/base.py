"""Abstract base class for the cache backend.

Defines the interface that all cache implementations must follow.
Includes both basic get/set operations and versioned cache invalidation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseCacheBackend(ABC):
    """Abstract cache backend interface.

    All implementations (Valkey, in-memory) must implement this interface
    so the rest of the system can work with any backend transparently.
    """

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Human-readable backend name for logging/stats."""

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    @abstractmethod
    def get(self, key: str) -> Any | None:
        """Get a value by key. Returns None on miss or error (fail-open)."""

    @abstractmethod
    def set(self, key: str, value: Any, timeout: int | None = None) -> None:
        """Set a value with optional timeout in seconds."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a key."""

    @abstractmethod
    def incr(self, key: str) -> int:
        """Atomically increment a key. Raises ValueError if key doesn't exist."""

    @abstractmethod
    def add(self, key: str, value: Any, timeout: int | None = None) -> bool:
        """Set key only if it doesn't exist. Returns True if set, False if already exists."""

    @abstractmethod
    def clear(self) -> None:
        """Clear all keys."""

    @abstractmethod
    def is_healthy(self) -> bool:
        """Check if the backend is reachable and operational."""
