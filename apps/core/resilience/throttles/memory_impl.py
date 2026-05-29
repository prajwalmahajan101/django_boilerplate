"""In-process sliding-window throttle primitive — for non-DRF call sites.

The existing throttle stack in this package (``valkey_impl``,
``drf_impl``) integrates with DRF's ``SimpleRateThrottle`` for view-
level rate limiting. ``InMemoryThrottle`` is a different beast: a
plain callable usable outside the DRF lifecycle — service methods that
fan out webhook deliveries, Celery tasks that hammer a third-party
API, custom CSP-report ingestion. None of those flow through a DRF
view; none can use the DRF throttle classes.

Per-process state (one deque per identifier under a single
``threading.Lock``) — fine for single-worker deployments and as a
fail-open fallback when Valkey is unavailable, but **not** safe across
multiple gunicorn workers. For cross-worker correctness use a
Valkey-backed throttle (see ``valkey_impl.py``).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class ThrottleResult:
    """Outcome of one :meth:`InMemoryThrottle.check` call.

    ``retry_after`` is seconds (float). ``reset_at`` is a unix timestamp
    (int) — when the oldest in-window timestamp falls out of the
    window.
    """

    allowed: bool
    limit: int
    remaining: int
    reset_at: int
    retry_after: float


class InMemoryThrottle:
    """Sliding-window rate limiter keyed by identifier."""

    def __init__(self) -> None:
        self._windows: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(
        self,
        identifier: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> ThrottleResult:
        """Slide the window for ``identifier`` and decide whether to allow.

        Args:
            identifier: Bucket key (e.g. ``f"webhook:{partner_id}"``).
            limit: Maximum allowed events in ``window_seconds``.
            window_seconds: Rolling window duration in seconds.
        """
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            window = self._windows.setdefault(identifier, deque())
            while window and window[0] < cutoff:
                window.popleft()
            current = len(window)
            if current >= limit:
                oldest = window[0]
                retry_after = max(0.0, oldest + window_seconds - now)
                return ThrottleResult(
                    allowed=False,
                    limit=limit,
                    remaining=0,
                    reset_at=int(oldest + window_seconds),
                    retry_after=retry_after,
                )
            window.append(now)
            return ThrottleResult(
                allowed=True,
                limit=limit,
                remaining=limit - (current + 1),
                reset_at=int(now + window_seconds),
                retry_after=0.0,
            )

    @property
    def backend_name(self) -> str:
        """Stable label surfaced in readiness probes."""
        return "memory"


__all__ = ["InMemoryThrottle", "ThrottleResult"]
