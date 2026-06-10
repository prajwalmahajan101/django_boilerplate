"""Backend protocol for api_log persistence."""

from __future__ import annotations

from typing import Protocol


class ApiLogBackend(Protocol):
    """A backend persists a single audit row.

    Implementations must be safe to call from a worker thread (the
    fire-and-forget queue's executor). They must not raise into the
    caller — failures should be logged and swallowed.
    """

    backend_name: str

    def persist(self, row: dict) -> None: ...
