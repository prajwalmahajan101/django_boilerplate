"""
External database connection utility using SQLAlchemy.

Provides a lightweight interface for querying external databases (not the
primary Django database). All SQLAlchemy imports are lazy to avoid loading
the library until it is actually needed.

Usage:
    from core.utils.db import build_url, execute_query, get_engine

    engine = get_engine(build_url(host="db.example.com", name="analytics"))
    result = execute_query(engine, "SELECT count(*) FROM events")
    print(result.scalar)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from threading import Lock
from types import SimpleNamespace
from typing import Any, Iterator, Sequence

from django.conf import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SqlRowSet
# ---------------------------------------------------------------------------

@dataclass
class SqlRowSet:
    """Wrapper around raw database rows with convenient accessors."""

    rows: list[tuple] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    rowcount: int = 0

    # -- Computed helpers ----------------------------------------------------

    @property
    def objects(self) -> list[SimpleNamespace]:
        """Return rows as a list of SimpleNamespace for attribute access."""
        return [
            SimpleNamespace(**dict(zip(self.columns, row)))
            for row in self.rows
        ]

    @property
    def first(self) -> SimpleNamespace | None:
        """Return the first row as a SimpleNamespace, or None."""
        if not self.rows:
            return None
        return SimpleNamespace(**dict(zip(self.columns, self.rows[0])))

    @property
    def scalar(self) -> Any:
        """Return the first column of the first row, or None."""
        if not self.rows:
            return None
        return self.rows[0][0]

    def __iter__(self) -> Iterator[SimpleNamespace]:
        return iter(self.objects)

    def __len__(self) -> int:
        return len(self.rows)

    def __bool__(self) -> bool:
        return len(self.rows) > 0


# ---------------------------------------------------------------------------
# URL builder
# ---------------------------------------------------------------------------

def build_url(
    *,
    host: str | None = None,
    port: int | str = 5432,
    name: str | None = None,
    user: str | None = None,
    password: str | None = None,
    driver: str = "postgresql+psycopg2",
) -> str:
    """Build a SQLAlchemy database URL from components.

    Falls back to Django ``DATABASES['default']`` settings for any value not
    explicitly provided.
    """
    db_settings = getattr(settings, "DATABASES", {}).get("default", {})

    host = host or db_settings.get("HOST", "localhost")
    port = int(port or db_settings.get("PORT", 5432))
    name = name or db_settings.get("NAME", "")
    user = user or db_settings.get("USER", "")
    password = password or db_settings.get("PASSWORD", "")

    from sqlalchemy.engine import make_url

    url = make_url(f"{driver}://{user}:{password}@{host}:{port}/{name}")
    return url.render_as_string(hide_password=False)


# ---------------------------------------------------------------------------
# Engine management
# ---------------------------------------------------------------------------

_engine_cache: dict[str, Any] = {}
_engine_cache_lock = Lock()


def get_engine(url: str, **kwargs: Any):
    """Return a cached SQLAlchemy Engine for *url*.

    Additional ``**kwargs`` are forwarded to ``create_engine`` only on first
    call for a given URL (subsequent calls return the cached instance).
    """
    cached = _engine_cache.get(url)
    if cached is not None:
        return cached

    with _engine_cache_lock:
        if url not in _engine_cache:
            from sqlalchemy import create_engine

            defaults: dict[str, Any] = {
                "pool_pre_ping": True,
                "pool_size": 5,
                "max_overflow": 10,
                "connect_args": {
                    "connect_timeout": 5,
                    "options": "-c statement_timeout=30000",
                },
            }
            defaults.update(kwargs)

            logger.info("Creating SQLAlchemy engine for %s", _mask_url(url))
            _engine_cache[url] = create_engine(url, **defaults)
        return _engine_cache[url]


def dispose_engine(url: str) -> None:
    """Dispose a single engine by URL and remove it from the cache."""
    with _engine_cache_lock:
        engine = _engine_cache.pop(url, None)

    if engine is not None:
        engine.dispose()
        logger.info("Disposed SQLAlchemy engine for %s", _mask_url(url))


def dispose_all_engines() -> None:
    """Dispose every cached engine. Intended for shutdown / atexit."""
    with _engine_cache_lock:
        engines = list(_engine_cache.values())
        _engine_cache.clear()

    for engine in engines:
        engine.dispose()
    if engines:
        logger.info("Disposed all SQLAlchemy engines (%d)", len(engines))


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------

_WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "TRUNCATE")


def execute_query(
    engine,
    sql: str,
    params: dict[str, Any] | Sequence[dict[str, Any]] | None = None,
) -> SqlRowSet:
    """Execute *sql* against *engine* and return a ``SqlRowSet``.

    Automatically commits for write statements (INSERT/UPDATE/DELETE/DDL).
    """
    from sqlalchemy import text

    stmt = text(sql)
    is_write = sql.strip().upper().startswith(_WRITE_PREFIXES)

    with engine.connect() as conn:
        cursor = conn.execute(stmt, params or {})

        if is_write:
            conn.commit()
            return SqlRowSet(rowcount=cursor.rowcount)

        rows = cursor.fetchall()
        columns = list(cursor.keys())
        return SqlRowSet(rows=[tuple(r) for r in rows], columns=columns, rowcount=cursor.rowcount)


def ping_engine(engine) -> bool:
    """Run a lightweight connectivity probe against *engine*.

    Returns ``True`` if a ``SELECT 1`` round-trip succeeds, ``False`` on any
    error (logged with ``exc_info``). Call this from health checks, readiness
    probes, and diagnostics instead of opening a connection inline.
    """
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.error("Engine connectivity probe failed", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _mask_url(url: str) -> str:
    """Replace password in a URL string with ``***``."""
    from sqlalchemy.engine import make_url

    u = make_url(url)
    return u.render_as_string(hide_password=True)
