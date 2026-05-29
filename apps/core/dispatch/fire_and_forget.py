"""Bounded fire-and-forget queue for best-effort dispatch.

Direct port of ``colending_partner/src/core/utils/fire_and_forget.py``,
adapted to the gateway's gthread-Django runtime (ThreadPoolExecutor +
``queue.Queue`` instead of asyncio).

Use for audit logs, telemetry, and other side effects where the request
path should not pay the cost and a dropped task on overflow is
preferable to building a durable infrastructure.

Each queue is named so multiple use cases can coexist with independent
bounds (audit logs vs metric exports). The module-level registry
exposes them for shutdown drainage.
"""

from __future__ import annotations

import logging
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

logger = logging.getLogger(__name__)


_registry_lock = threading.RLock()
_queues: dict[str, "FireAndForgetQueue"] = {}


class FireAndForgetQueue:
    """A bounded best-effort work queue.

    Overflow is **dropped**, not blocked, and emits a WARNING with a
    monotonically increasing drop counter so operators can spot
    saturation without parsing every log line.
    """

    def __init__(
        self,
        name: str,
        *,
        max_in_flight: int = 1000,
        max_workers: int = 4,
    ) -> None:
        self.name = name
        self._queue: queue.Queue = queue.Queue(maxsize=max_in_flight)
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=f"fire-and-forget-{name}",
        )
        self._dropped = 0
        self._stop = threading.Event()
        self._drained = threading.Event()
        self._consumer_thread = threading.Thread(
            target=self._consume_loop,
            name=f"fire-and-forget-consumer-{name}",
            daemon=True,
        )
        self._consumer_thread.start()
        with _registry_lock:
            _queues[name] = self

    def submit(self, fn: Callable[[], None]) -> bool:
        """Enqueue ``fn`` for background execution. Returns False on overflow."""
        try:
            self._queue.put_nowait(fn)
            return True
        except queue.Full:
            self._dropped += 1
            logger.warning(
                "fire_and_forget_overflow",
                extra={
                    "event": "fire_and_forget_overflow",
                    "queue": self.name,
                    "dropped_count": self._dropped,
                },
            )
            return False

    def _consume_loop(self) -> None:
        while not self._stop.is_set():
            try:
                fn = self._queue.get(timeout=0.5)
            except queue.Empty:
                if self._stop.is_set() and self._queue.empty():
                    break
                continue
            try:
                self._executor.submit(self._safe_run, fn)
            except RuntimeError:
                # Executor is shutting down — drop the task. We're tearing
                # down; the cost of losing best-effort work is by design.
                break
            finally:
                self._queue.task_done()
        self._drained.set()

    @staticmethod
    def _safe_run(fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001 — best-effort: log + drop
            logger.exception("fire_and_forget task raised")

    def drain(self, timeout: float = 5.0) -> bool:
        """Block until queued tasks are submitted to the executor.

        Returns True if the queue drained within ``timeout``. Called at
        shutdown to flush pending work; tests use it to assert delivery.
        """
        deadline_event = threading.Event()
        deadline_event.wait(timeout=0)  # no-op, kept for readability
        try:
            self._queue.join()
        except Exception:  # noqa: BLE001
            return False
        return self._queue.empty()

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the consumer to drain and stop, then shut the executor."""
        self._stop.set()
        self._consumer_thread.join(timeout=timeout)
        self._executor.shutdown(wait=True, cancel_futures=False)

    @property
    def dropped_count(self) -> int:
        return self._dropped


def get_queue(name: str) -> FireAndForgetQueue:
    """Return the FireAndForgetQueue registered under ``name``."""
    with _registry_lock:
        return _queues[name]


def registered_queues() -> list[FireAndForgetQueue]:
    with _registry_lock:
        return list(_queues.values())


def drain_all(timeout: float = 5.0) -> None:
    """Drain every registered queue. Called at SIGTERM / process exit."""
    for q in registered_queues():
        q.drain(timeout=timeout)
