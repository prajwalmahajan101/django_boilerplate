#!/usr/bin/env python3
"""Fail when an ``apps/core/`` module declares mutable module-level state
without a sibling lock or documented waiver.

Three review cycles in a row landed the same bug: a module-level
``dict`` / ``set`` / ``list`` registry was added to the request path
without a ``threading.Lock`` / ``threading.RLock`` / ``threading.local``
guard. Each time the fix was the same — add a lock, snapshot under
lock, document in ``docs/thread-safety.md``. This script encodes the
"add a lock" half so the fourth instance fails at pre-commit instead
of code review.

What is flagged:
    A module-level ``Assign`` / ``AnnAssign`` whose target is a bare
    name (not ``ClassName.attr``), whose value is one of the mutable
    container literals or constructors (``{}``, ``set()``, ``[]``,
    ``dict(...)``, ``list(...)``, ``set(...)``), and which is **mutated
    elsewhere in the same module** (``name[k] = v``, ``del name[k]``,
    ``name.append(...)`` / ``add`` / ``update`` / ``pop`` / ``clear``
    / ``setdefault`` / ``remove`` / ``discard`` / ``extend``), in a
    module that does NOT also declare, at module scope, any of:

        threading.Lock()
        threading.RLock()
        threading.local()

What is exempt:
    * Read-only-after-import constants (``__all__``, ``urlpatterns``,
      lookup tables not mutated anywhere in the module). Detected by
      absence of any mutation operation on the same name.
    * Dunder names (``__all__``, ``__path__``, …).
    * Frozen containers — ``frozenset(...)``, tuple literals, ``Final``-
      annotated constants — are immutable and not flagged.
    * Test modules (``tests/`` in path, or filename ``test_*.py``).
    * A waiver comment on the offending line:
          ``# thread-safety: <reason>``
      Use sparingly; the reason should explain why the lock is not
      needed (e.g. ``lru_cache``, ``settings_changed`` invalidation,
      single-writer at import time, …).

Exit codes:
    0 — clean.
    1 — at least one unguarded module-level mutable container; offending
        ``file:lineno: name`` lines printed.

Run manually::

    python scripts/check_thread_safety.py

Wire as a pre-commit hook so the same check runs on every commit that
touches a file anywhere under ``apps/core/``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = ROOT / "apps" / "core"

_MUTABLE_CALL_NAMES = {"dict", "set", "list"}
_LOCK_CALL_LEAVES = {"Lock", "RLock", "local"}
_WAIVER_TAG = "thread-safety:"
_MUTATING_METHODS = {
    "append",
    "extend",
    "insert",
    "remove",
    "pop",
    "clear",
    "add",
    "discard",
    "update",
    "setdefault",
    "popitem",
}


def _is_mutable_container_value(value: ast.AST | None) -> bool:
    """Return True when *value* is a mutable container literal or call."""
    if value is None:
        return False
    if isinstance(value, ast.Dict):
        return True
    if isinstance(value, ast.List):
        return True
    if isinstance(value, ast.Set):
        return True
    if isinstance(value, ast.Call):
        func = value.func
        # Plain name: dict(), set(), list().
        if isinstance(func, ast.Name) and func.id in _MUTABLE_CALL_NAMES:
            return True
    return False


def _is_lock_call(value: ast.AST) -> bool:
    """Return True when *value* is ``threading.Lock()`` / ``RLock()`` / ``local()``."""
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    if isinstance(func, ast.Attribute) and func.attr in _LOCK_CALL_LEAVES:
        return True
    if isinstance(func, ast.Name) and func.id in _LOCK_CALL_LEAVES:
        return True
    return False


def _module_has_lock(tree: ast.Module) -> bool:
    """Return True when *tree* declares a module-level lock primitive."""
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value if isinstance(node, ast.Assign) else node.value
            if value is not None and _is_lock_call(value):
                return True
    return False


def _line_has_waiver(source_lines: list[str], lineno: int) -> bool:
    """Return True when the offending line carries the waiver comment."""
    if lineno < 1 or lineno > len(source_lines):
        return False
    return _WAIVER_TAG in source_lines[lineno - 1]


def _collect_mutated_names(tree: ast.Module) -> set[str]:
    """Return every bare name that is mutated anywhere in *tree*.

    Catches ``name[k] = v``, ``del name[k]``, and method calls in
    ``_MUTATING_METHODS`` on a bare name. Anything not in this set is
    treated as read-only-after-import (frozen by convention).
    """
    mutated: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                    mutated.add(target.value.id)
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name):
                mutated.add(node.target.id)
            elif isinstance(node.target, ast.Subscript) and isinstance(node.target.value, ast.Name):
                mutated.add(node.target.value.id)
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                    mutated.add(target.value.id)
        elif isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.attr in _MUTATING_METHODS
            ):
                mutated.add(func.value.id)
    return mutated


def _module_violations(tree: ast.Module, source_lines: list[str]) -> list[tuple[int, str]]:
    """Return ``(lineno, name)`` for every unguarded mutated container."""
    if _module_has_lock(tree):
        return []

    mutated = _collect_mutated_names(tree)
    if not mutated:
        return []

    out: list[tuple[int, str]] = []
    for node in tree.body:
        targets: list[ast.AST] = []
        value: ast.AST | None = None

        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue

        if not _is_mutable_container_value(value):
            continue

        for target in targets:
            if not isinstance(target, ast.Name):
                continue  # ClassName.attr, tuple-unpack, etc.
            if target.id.startswith("__"):
                continue  # dunders like __all__
            if target.id not in mutated:
                continue  # read-only after import
            if _line_has_waiver(source_lines, node.lineno):
                continue
            out.append((node.lineno, target.id))

    return out


def _is_test_path(path: Path) -> bool:
    """Test modules are exempt — fixtures share mutable state by design."""
    if "tests" in path.parts:
        return True
    return path.name.startswith("test_")


def main() -> int:
    failed = False
    for path in sorted(CORE_ROOT.rglob("*.py")):
        if _is_test_path(path):
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            print(f"{path}: syntax error: {exc}", file=sys.stderr)
            failed = True
            continue
        source_lines = source.splitlines()
        for lineno, name in _module_violations(tree, source_lines):
            rel = path.relative_to(ROOT)
            print(
                f"{rel}:{lineno}: module-level mutable {name!r} without a "
                f"sibling threading.Lock / RLock / local()"
            )
            failed = True

    if failed:
        print(
            "\nUnguarded module-level mutable state in apps/core/ — see "
            "docs/thread-safety.md for the documented patterns. Either "
            "add a sibling threading.Lock / RLock / local() at module "
            "scope, or annotate the assignment line with "
            "'# thread-safety: <reason>' (e.g. 'lru_cache', "
            "'settings_changed invalidation', 'import-time only').",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
