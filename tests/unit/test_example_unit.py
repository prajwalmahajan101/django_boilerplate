"""Example unit test — no DB, no cache, no network.

Demonstrates the unit-layer contract: every boundary is mocked, the
test runs in microseconds, and removing/breaking infrastructure does
not affect the result.
"""

from __future__ import annotations

from unittest.mock import MagicMock


def test_pure_function_no_io():
    """A unit test of a pure function: input → output, no side effects."""

    def normalise_email(addr: str) -> str:
        return addr.strip().lower()

    assert normalise_email(" Alice@Example.COM ") == "alice@example.com"


def test_collaborator_is_mocked():
    """A unit test that mocks the boundary instead of calling it."""

    class Notifier:
        def __init__(self, transport):
            self.transport = transport

        def notify(self, msg: str) -> bool:
            return self.transport.send(msg)

    transport = MagicMock()
    transport.send.return_value = True

    assert Notifier(transport).notify("hi") is True
    transport.send.assert_called_once_with("hi")
