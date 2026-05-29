"""``best_effort_atomic`` — best-effort transactional write helper.

Wraps :func:`django.db.transaction.atomic` with a ``try / except`` that
**logs and swallows** any exception, so a caller can fire off audit /
tracking / outcome writes that **must not fail the operation that
preceded them**. The helper exists so the intent is named, not
hand-rolled at every call site.

Use this only for writes whose failure mode is "log and move on" — audit
fan-out, telemetry rollups, last-used stamps. Never for the
authoritative write the caller's response depends on.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from django.db import transaction


@contextmanager
def best_effort_atomic(
    label: str,
    *,
    logger: logging.Logger | None = None,
    using: str | None = None,
) -> Iterator[None]:
    """Run a transactional block; log + swallow any exception.

    Args:
        label: Short, action-oriented identifier folded into the
            warning log line (e.g. ``"persist api_log row"``). Reads as
            a verb phrase — the line is ``"failed to %s"``.
        logger: Logger to emit on failure. Defaults to this module's
            logger; pass the caller's module logger when correlation
            with the caller's namespace matters.
        using: Database alias forwarded to ``transaction.atomic``.

    Yields:
        ``None`` — the caller runs its work inside the block.
    """
    log = logger or logging.getLogger(__name__)
    try:
        with transaction.atomic(using=using):
            yield
    except Exception:
        log.warning("failed to %s", label, exc_info=True)


__all__ = ["best_effort_atomic"]
