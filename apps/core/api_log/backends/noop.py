"""No-op backend — used in tests + as the fail-open default."""

from __future__ import annotations


class NoopApiLogBackend:
    """Fail-open ``api_log`` backend; retains rows in-memory for test assertions."""

    backend_name = "noop"

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def persist(self, row: dict) -> None:
        # Retained in-memory so unit tests can assert what would have
        # been written without involving the ORM. Production uses the
        # noop backend purely as a fail-open — the list still grows
        # unbounded, so prod should never select it.
        self.rows.append(row)
