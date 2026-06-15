"""Reusable query-parameter-to-ORM-filter extraction.

Dormant: ships in-tree for downstream forks but is not on the request path
today (zero in-tree callers as of M2). Omitted from the coverage gate. The
dormant-import AST gate scheduled for M3 will fail the build if anything
under ``apps/`` imports from this module without a matching integration test.
"""

from __future__ import annotations

from typing import Any

from core.exceptions.repository import InvalidInputError

_BOOL_TRUE = frozenset({"true", "1", "yes"})
_BOOL_FALSE = frozenset({"false", "0", "no"})


class FilterParam:
    """Declares a single query parameter that maps to an ORM filter key.

    Args:
        query_param: Name in the URL query string (``?key=value``).
        orm_field: Key passed to ``.filter()``. Defaults to *query_param*.
        coerce: Target type — ``int``, ``bool``, or ``str`` (default).
    """

    __slots__ = ("coerce", "orm_field", "query_param")

    def __init__(
        self,
        query_param: str,
        orm_field: str | None = None,
        coerce: type = str,
    ) -> None:
        self.query_param = query_param
        self.orm_field = orm_field or query_param
        self.coerce = coerce


def extract_filters(
    query_params,
    filter_params: list[FilterParam],
) -> dict[str, Any]:
    """Extract and coerce declared query params into an ORM filter dict.

    Missing params are silently skipped (not supplied = no filter).

    Type-coercion failures from :func:`_coerce` propagate as
    ``InvalidInputError``; the DRF handler envelopes them as a 400
    response with code ``INVALID_INPUT``.
    """
    filters: dict[str, Any] = {}
    for fp in filter_params:
        raw = query_params.get(fp.query_param)
        if raw is None:
            continue
        filters[fp.orm_field] = _coerce(raw, fp.coerce, fp.query_param)
    return filters


def _coerce(raw: str, target: type, param_name: str) -> Any:
    """Coerce a raw query-param string to the declared type."""
    if target is int:
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise InvalidInputError(f"Parameter '{param_name}' must be an integer.") from exc
    if target is bool:
        lower = raw.strip().lower()
        if lower in _BOOL_TRUE:
            return True
        if lower in _BOOL_FALSE:
            return False
        raise InvalidInputError(f"Parameter '{param_name}' must be a boolean (true/false).")
    return raw
