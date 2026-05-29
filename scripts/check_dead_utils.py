#!/usr/bin/env python3
"""Fail when a public symbol under ``apps/core/`` has no callers.

Rules:
  * Walk every ``.py`` file under ``apps/core/``.
  * Collect top-level public symbols — module-level ``def``/``async def``,
    ``class``, and bare-name assignments — whose name does not start with
    ``_``.
  * For each symbol, grep the rest of the tree (excluding the defining
    file, migrations, ``__pycache__``, and the dead-utils tooling itself)
    for at least one reference. Plain string match — false positives are
    cheap, false negatives are expensive.
  * Symbols listed in ``scripts/dead_utils_allowlist.json`` (a flat
    ``["module.path:Name", ...]`` array) are exempt. Use the allowlist
    when a symbol is part of a public surface re-exported elsewhere
    (e.g. ``__all__``) or kept for SDK consumers that live outside the
    repo.

Exits 1 on the first unexplained orphan with a pointer to the file and
the allowlist key to add if the symbol is intentionally exported.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_ROOT = REPO_ROOT / "apps" / "core"
ALLOWLIST_PATH = Path(__file__).resolve().parent / "dead_utils_allowlist.json"

SCAN_ROOTS = [REPO_ROOT / "apps", REPO_ROOT / "config", REPO_ROOT / "tests"]
SKIP_DIR_NAMES = {"__pycache__", ".pytest_cache", "migrations"}


def _module_dotted(path: Path) -> str:
    rel = path.relative_to(REPO_ROOT / "apps").with_suffix("")
    return ".".join(rel.parts)


def _collect_public_symbols(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            if not node.name.startswith("_"):
                names.append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    names.append(target.id)
    return names


def _iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        yield path


def _load_allowlist() -> set[str]:
    if not ALLOWLIST_PATH.exists():
        return set()
    try:
        return set(json.loads(ALLOWLIST_PATH.read_text()))
    except (OSError, json.JSONDecodeError):
        return set()


def _has_reference(name: str, defining_file: Path) -> bool:
    needle = name
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in _iter_python_files(root):
            if path == defining_file:
                continue
            if path.name == "check_dead_utils.py":
                continue
            try:
                if needle in path.read_text(encoding="utf-8"):
                    return True
            except OSError:
                continue
    return False


def main() -> int:
    allowlist = _load_allowlist()
    orphans: list[tuple[str, Path]] = []
    for path in _iter_python_files(CORE_ROOT):
        module = _module_dotted(path)
        for name in _collect_public_symbols(path):
            key = f"{module}:{name}"
            if key in allowlist:
                continue
            if not _has_reference(name, path):
                orphans.append((key, path))

    if not orphans:
        return 0

    print("Dead public symbols under apps/core/ (no callers found):", file=sys.stderr)
    for key, path in orphans:
        print(f"  {key}   ({path.relative_to(REPO_ROOT)})", file=sys.stderr)
    print(
        "\nIf any of these are intentionally exported (re-exports, SDK surface), "
        f"add the matching keys to {ALLOWLIST_PATH.relative_to(REPO_ROOT)}.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
