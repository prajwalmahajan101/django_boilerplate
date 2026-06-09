"""Unit tests for the global-throttle Lua script cache.

Exercises the module-level cache + ``ensure_loaded`` idempotency
without touching a live Valkey — the client factory is a fake.
"""

from __future__ import annotations

from threading import Thread
from unittest.mock import MagicMock

import pytest
from core.resilience.throttles import global_lua


@pytest.fixture(autouse=True)
def _isolated_cache():
    global_lua.reset()
    yield
    global_lua.reset()


def test_get_sha_returns_none_before_load() -> None:
    assert global_lua.get_sha() is None


def test_ensure_loaded_caches_sha() -> None:
    client = MagicMock()
    client.script_load.return_value = "abc123"
    sha = global_lua.ensure_loaded(lambda: client)
    assert sha == "abc123"
    assert global_lua.get_sha() == "abc123"
    client.script_load.assert_called_once()


def test_ensure_loaded_is_idempotent() -> None:
    client = MagicMock()
    client.script_load.return_value = "abc123"
    factory = MagicMock(return_value=client)
    global_lua.ensure_loaded(factory)
    global_lua.ensure_loaded(factory)
    global_lua.ensure_loaded(factory)
    factory.assert_called_once()
    client.script_load.assert_called_once()


def test_reset_clears_cache_for_next_load() -> None:
    client = MagicMock()
    client.script_load.side_effect = ["sha1", "sha2"]
    global_lua.ensure_loaded(lambda: client)
    global_lua.reset()
    assert global_lua.get_sha() is None
    global_lua.ensure_loaded(lambda: client)
    assert global_lua.get_sha() == "sha2"


def test_load_failure_returns_none_and_does_not_cache() -> None:
    client = MagicMock()
    client.script_load.side_effect = RuntimeError("valkey down")
    assert global_lua.ensure_loaded(lambda: client) is None
    assert global_lua.get_sha() is None


def test_concurrent_calls_load_once() -> None:
    client = MagicMock()
    client.script_load.return_value = "abc123"
    factory = MagicMock(return_value=client)

    threads = [Thread(target=lambda: global_lua.ensure_loaded(factory)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Double-checked locking: exactly one SCRIPT LOAD even under contention.
    client.script_load.assert_called_once()
