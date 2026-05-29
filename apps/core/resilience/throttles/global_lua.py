"""Process-wide Lua-script cache for ``GlobalThrottle``.

The atomic O(1) sliding-window check lives on its own (different
algorithm + different Lua script from the per-ident throttle), so its
script-SHA cache and load helper are kept here rather than entangled
with the base ``ValkeyRateThrottle`` class. Both are process-wide and
double-checked-locked so concurrent throttle instantiations don't
race on the first ``SCRIPT LOAD`` round-trip.
"""

from __future__ import annotations

import logging
from threading import Lock
from typing import Callable

from core.resilience.throttles.lua_scripts import GLOBAL_THROTTLE_LUA_SCRIPT

logger = logging.getLogger(__name__)

_sha: str | None = None
_lock = Lock()


def get_sha() -> str | None:
    """Return the cached script SHA, or ``None`` if Lua is unavailable."""
    return _sha


def reset() -> None:
    """Clear the cache so the next call re-loads the script.

    Called by ``GlobalThrottle._allow_request_global_atomic`` on
    ``NOSCRIPT``-style errors so the next request retries the load
    instead of falling back forever.
    """
    global _sha
    with _lock:
        _sha = None


def ensure_loaded(client_factory: Callable[[], object]) -> str | None:
    """Idempotently load the global throttle script into Valkey.

    ``client_factory`` is the throttle's ``_get_valkey_client`` bound
    method — we accept it as a callable so this module stays free of
    any dependency on the throttle base class. Returns the cached SHA
    (loading it if necessary), or ``None`` on load failure.
    """
    global _sha
    if _sha is not None:
        return _sha

    with _lock:
        if _sha is not None:
            return _sha

        try:
            client = client_factory()
            _sha = client.script_load(GLOBAL_THROTTLE_LUA_SCRIPT)
        except Exception as exc:
            logger.warning(
                "Failed to load global throttle Lua script: %s. "
                "Falling back to non-atomic implementation.",
                str(exc),
            )
            _sha = None

        return _sha
