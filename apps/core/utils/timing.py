"""``perf_timer`` — named wall-clock timer for audit ``elapsed_ms`` fields.

Several outbound call sites repeat the same idiom::

    start = time.perf_counter()
    try:
        ...
    except SomeError:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        ...
    elapsed_ms = int((time.perf_counter() - start) * 1000)

The shape is tiny but the duplication adds noise and is easy to get
subtly wrong (units, rounding, off-by-one). :func:`perf_timer` names the
intent and centralises the multiplier::

    with perf_timer() as t:
        ...
    audit(elapsed_ms=t.elapsed_ms)

Reads ``perf_counter`` (monotonic), so the value is safe to use as a
duration even across system-clock adjustments.

Distinct from :func:`apps.core.utils.logging.log_duration`, which both
times and emits a log/metric record on exit. ``perf_timer`` is the
silent variant: hand the elapsed value to an audit row, a metric
counter, or a percentile probe without forcing a log line.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class PerfTimer:
    """Holder for the timer's running and final elapsed values.

    Attributes:
        elapsed_ms: Milliseconds elapsed from ``__enter__`` until either
            the current moment (while the block is open) or the moment
            the block exited (after it closes). Float — sub-ms precision
            matters for cache-hit reads, 304 paths, in-memory fallbacks.
    """

    _start: float = field(default_factory=time.perf_counter)
    _end: float | None = None

    @property
    def elapsed_ms(self) -> float:
        """Milliseconds elapsed since the block entered.

        While the block is open, returns running elapsed; after it
        closes, returns the frozen close-time value.
        """
        end = self._end if self._end is not None else time.perf_counter()
        return (end - self._start) * 1000

    def stop(self) -> None:
        """Freeze ``elapsed_ms`` at the current monotonic instant."""
        self._end = time.perf_counter()


@contextmanager
def perf_timer() -> Iterator[PerfTimer]:
    """Yield a :class:`PerfTimer` whose ``.elapsed_ms`` is valid mid-block and after.

    The block can read ``.elapsed_ms`` at any point — useful for
    stamping the success-side audit row inside the try and the
    failure-side row in the except off the same timer.
    """
    timer = PerfTimer()
    try:
        yield timer
    finally:
        timer.stop()


__all__ = ["PerfTimer", "perf_timer"]
