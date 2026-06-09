"""Rate-string parser shared by every throttle backend.

Centralises the ``"<int>/<unit>"`` grammar so a single source of truth
covers both the DRF throttle classes (``valkey_impl``, ``drf_impl``)
and the standalone :class:`InMemoryThrottle` primitive.

The pre-existing UserTierThrottle / BurstThrottle / GlobalThrottle
classes already live under ``apps.core.resilience.throttles`` as DRF
``SimpleRateThrottle`` subclasses — they are the scope registry; this
module is the parsing helper they (and any new non-DRF call site)
share.
"""

from __future__ import annotations

import re

_UNIT_TO_SECONDS: dict[str, int] = {
    "s": 1,
    "sec": 1,
    "second": 1,
    "m": 60,
    "min": 60,
    "minute": 60,
    "h": 3600,
    "hour": 3600,
    "d": 86_400,
    "day": 86_400,
}


def parse_rate(rate: str) -> tuple[int, int]:
    """Parse a ``"<int>/<unit>"`` rate string into ``(limit, window_seconds)``.

    Accepts short and long unit names (``s``/``sec``/``second``,
    ``m``/``min``/``minute``, ``h``/``hour``, ``d``/``day``).

    Raises:
        ValueError: The string doesn't match ``<int>/<unit>`` or the
            unit isn't one of the known ones.
    """
    match = re.fullmatch(r"\s*(\d+)\s*/\s*(\w+)\s*", rate)
    if not match:
        raise ValueError(f"Invalid rate '{rate}'. Expected '<int>/<unit>' (e.g. '100/min').")
    limit_str, unit = match.groups()
    unit = unit.lower()
    if unit not in _UNIT_TO_SECONDS:
        raise ValueError(f"Unknown rate unit '{unit}'. Use s, m, h, or d (or longer aliases).")
    return int(limit_str), _UNIT_TO_SECONDS[unit]


__all__ = ["parse_rate"]
