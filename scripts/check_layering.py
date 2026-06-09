#!/usr/bin/env python3
"""Fail when ``apps/core/`` imports a sibling domain app or ``config``.

The repo-wide invariant (``apps/core/CLAUDE.md``, "Never mounted as a
standalone feature. Shared infrastructure only. Nothing in core
imports from domain apps."): ``core`` must never import from
``apps.<domain>`` (today: ``accounts``; tomorrow: anything dropped in
next to it) or from ``config``. Core reads project state only through
``django.conf.settings``; keeping the direction one-way is what makes
``apps.core`` liftable into the next project unchanged.

This script enforces the rule mechanically so it cannot regress
silently. It AST-walks every ``.py`` file under ``apps/core/`` and
fails on the first offending import.

The walk understands both spellings the repo uses for the same module:
``core.x`` (via the ``apps/`` entry on ``sys.path`` injected by
``manage.py``) and ``apps.core.x`` (via the project root). Forbidden
imports under either spelling are reported.

Exit codes:
    ``0`` — every core module imports only stdlib / third-party / core.
    ``1`` — one or more forbidden imports; offending file:line and
            dotted module are printed.

Run manually via::

    python scripts/check_layering.py

Wire as a pre-commit hook so the same check runs on every commit that
touches a file anywhere under ``apps/core/``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = ROOT / "apps" / "core"


# Discover sibling domain apps dynamically so adding a new app under
# apps/ does NOT require editing this script. Anything that is a
# directory under apps/ and is not "core" is treated as a forbidden
# import target from inside core.
def _domain_apps() -> tuple[str, ...]:
    apps_dir = ROOT / "apps"
    return tuple(
        sorted(
            p.name
            for p in apps_dir.iterdir()
            if p.is_dir() and p.name != "core" and (p / "__init__.py").exists()
        )
    )


def _forbidden_prefixes() -> tuple[str, ...]:
    """Build the forbidden-prefix tuple for every spelling we accept.

    ``config`` is always forbidden — settings are reached via
    ``django.conf.settings``, never by importing the module directly.
    """
    out: list[str] = ["config"]
    for app in _domain_apps():
        out.extend([f"apps.{app}", app])
    return tuple(out)


def _violations(path: Path, forbidden: tuple[str, ...]) -> list[tuple[int, str]]:
    """Return ``(lineno, dotted)`` for every forbidden import in *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for prefix in forbidden:
                if node.module == prefix or node.module.startswith(prefix + "."):
                    out.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                for prefix in forbidden:
                    if alias.name == prefix or alias.name.startswith(prefix + "."):
                        out.append((node.lineno, alias.name))
    return out


def _is_test_path(path: Path) -> bool:
    """Test code legitimately crosses app boundaries via fixtures."""
    return "tests" in path.parts


def main() -> int:
    forbidden = _forbidden_prefixes()
    failed = False
    for path in sorted(CORE_ROOT.rglob("*.py")):
        if _is_test_path(path):
            continue
        for lineno, dotted in _violations(path, forbidden):
            rel = path.relative_to(ROOT)
            print(f"{rel}:{lineno}: forbidden import in apps/core/: {dotted}")
            failed = True
    if failed:
        print(
            "\napps.core must not import from a sibling domain app or from "
            "config (see apps/core/CLAUDE.md). Move the shared value behind "
            "django.conf.settings or refactor the helper.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
