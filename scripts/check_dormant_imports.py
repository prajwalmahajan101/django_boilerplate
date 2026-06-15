#!/usr/bin/env python3
"""Fail when live code imports a dormant module.

Nine modules under ``apps/core/`` ship in-tree for downstream forks
but have zero in-tree request-path callers today. They are omitted
from the coverage gate (``.coveragerc`` ``[run] omit``) and carry a
``Dormant:`` callout in their module docstring. The convention only
works if nobody silently wires one back into the request path
without an integration test — which is exactly what this gate
enforces at pre-commit time.

What is flagged:
    An ``Import`` or ``ImportFrom`` node anywhere under ``apps/`` or
    ``config/`` whose target resolves to a dormant module's dotted
    name (e.g. ``core.utils.s3``).

What is exempt:
    * The dormant modules themselves — dormant→dormant imports stay
      inside the dormancy boundary and don't reopen the request path
      (e.g. ``core.utils.s3 → core.utils.aws``).
    * Test modules (``tests/`` in path, or filename ``test_*.py``) —
      tests exercising a dormant module ARE the integration-test
      escape hatch the policy contemplates.
    * A waiver comment on the offending import's start line:
          ``# allow-dormant-import: <reason>``
      Use sparingly. The reason should describe the narrow seam
      (atexit hook, integration test, single-shot management
      command) that justifies pulling a dormant module without
      promoting it to live.

Source of truth:
    The dormant set is read from ``.coveragerc``'s ``[run] omit``
    list (entries under ``apps/``). Each entry is cross-checked
    against the file's module docstring for the literal substring
    ``Dormant:``. A mismatch (omit without docstring marker, or
    docstring marker without omit) exits 2 with a ``dormant-set
    drift`` message before any imports are walked — keeps the two
    halves of the policy honest.

Exit codes:
    0 — clean.
    1 — at least one unwaived dormant import.
    2 — dormant-set drift (config / docstring disagreement).

Run manually::

    python scripts/check_dormant_imports.py

Wired as a pre-commit hook so the same check runs on every commit
that touches a file under ``apps/`` or ``config/``.
"""

from __future__ import annotations

import ast
import configparser
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_WAIVER_TAG = "allow-dormant-import:"
_WAIVER_RE = re.compile(r"#\s*allow-dormant-import:\s*\S+")
# ``Dormant:`` or ``Dormant (transitively):`` — both forms used in tree.
_MARKER_RE = re.compile(r"\bDormant\b[^:\n]*:")


def _strip_inline_comment(line: str) -> str:
    """Drop trailing ``# ...`` from a ``.coveragerc`` ``omit`` entry."""
    hash_idx = line.find("#")
    if hash_idx == -1:
        return line
    return line[:hash_idx]


def _load_omit_paths(cwd: Path) -> list[str]:
    """Return ``apps/...`` entries from ``.coveragerc`` ``[run] omit``."""
    rc_path = cwd / ".coveragerc"
    parser = configparser.ConfigParser()
    parser.read(rc_path, encoding="utf-8")
    raw = parser.get("run", "omit", fallback="")
    entries = []
    for line in raw.splitlines():
        cleaned = _strip_inline_comment(line).strip()
        if not cleaned:
            continue
        if cleaned.startswith("apps/") and "*" not in cleaned:
            entries.append(cleaned)
    return entries


def _module_docstring(path: Path) -> str | None:
    """Return *path*'s module docstring, or ``None`` if not parseable."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return None
    return ast.get_docstring(tree)


def _scan_dormant_markers(cwd: Path) -> set[str]:
    """Return every ``apps/...py`` path whose module docstring contains ``Dormant:``."""
    found: set[str] = set()
    apps_dir = cwd / "apps"
    if not apps_dir.is_dir():
        return found
    for path in apps_dir.rglob("*.py"):
        if "tests" in path.parts or path.name.startswith("test_"):
            continue
        doc = _module_docstring(path)
        if doc and _MARKER_RE.search(doc):
            found.add(str(path.relative_to(cwd)))
    return found


def _check_drift(omit: list[str], markers: set[str], cwd: Path) -> list[str]:
    """Return drift messages — empty list means the two halves agree."""
    msgs = []
    omit_set = set(omit)
    for entry in omit_set - markers:
        full = cwd / entry
        if not full.is_file():
            msgs.append(
                f"dormant-set drift: {entry} omitted in .coveragerc but file does not exist"
            )
            continue
        msgs.append(
            f"dormant-set drift: {entry} omitted in .coveragerc but missing 'Dormant:' "
            "module-docstring marker"
        )
    for entry in markers - omit_set:
        msgs.append(
            f"dormant-set drift: {entry} carries 'Dormant:' docstring marker but is not in "
            ".coveragerc [run] omit"
        )
    return msgs


def _dotted_names_for(entry: str) -> str:
    """Map ``apps/core/utils/s3.py`` → ``core.utils.s3``."""
    # Strip leading ``apps/`` and trailing ``.py``.
    relative = entry[len("apps/") :] if entry.startswith("apps/") else entry
    if relative.endswith(".py"):
        relative = relative[: -len(".py")]
    return relative.replace("/", ".")


def _is_test_path(path: Path) -> bool:
    if "tests" in path.parts:
        return True
    return path.name.startswith("test_")


def _resolve_import_names(node: ast.Import | ast.ImportFrom, path: Path, cwd: Path) -> list[str]:
    """Return the candidate dotted names a node imports.

    For ``from foo import bar`` returns BOTH ``foo`` and ``foo.bar`` so a
    submodule import is flagged whether the writer named the module on
    the left or right of ``import``.
    """
    candidates: list[str] = []
    if isinstance(node, ast.Import):
        candidates.extend(alias.name for alias in node.names)
        return candidates

    # ast.ImportFrom
    base = node.module or ""
    if node.level:
        # Relative import — resolve against the file's package path.
        parts = list(path.relative_to(cwd).with_suffix("").parts)
        # First part is ``apps``; drop it to mirror dotted-name shape.
        if parts and parts[0] == "apps":
            parts = parts[1:]
        # ``parts[-1]`` is the importing module's own basename; ascend
        # ``node.level`` directories from its parent.
        anchor = parts[:-1]
        if node.level > len(anchor):
            # Out-of-tree relative import; can't resolve confidently.
            return candidates
        prefix_parts = anchor[: len(anchor) - node.level + 1]
        if base:
            full_base = ".".join([*prefix_parts, base])
        else:
            full_base = ".".join(prefix_parts)
    else:
        full_base = base

    if full_base:
        candidates.append(full_base)
        for alias in node.names:
            if alias.name == "*":
                continue
            candidates.append(f"{full_base}.{alias.name}")
    return candidates


def _line_has_waiver(source_lines: list[str], lineno: int) -> bool:
    if lineno < 1 or lineno > len(source_lines):
        return False
    return bool(_WAIVER_RE.search(source_lines[lineno - 1]))


def _walk_targets(cwd: Path) -> list[Path]:
    targets: list[Path] = []
    for top in ("apps", "config"):
        root = cwd / top
        if root.is_dir():
            targets.extend(sorted(root.rglob("*.py")))
    return targets


def main() -> int:
    cwd = Path.cwd()
    rc = cwd / ".coveragerc"
    if not rc.is_file():
        print(f"check_dormant_imports: no .coveragerc at {rc}", file=sys.stderr)
        return 2

    omit_paths = _load_omit_paths(cwd)
    markers = _scan_dormant_markers(cwd)

    drift = _check_drift(omit_paths, markers, cwd)
    if drift:
        for msg in drift:
            print(msg, file=sys.stderr)
        return 2

    dormant_files = {Path(entry) for entry in omit_paths}
    dormant_dotted = {_dotted_names_for(entry) for entry in omit_paths}

    failed = False
    violation_count = 0
    for path in _walk_targets(cwd):
        rel = path.relative_to(cwd)
        if rel in dormant_files:
            continue
        if _is_test_path(rel):
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            print(f"{rel}: syntax error: {exc}", file=sys.stderr)
            failed = True
            continue
        source_lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Import | ast.ImportFrom):
                continue
            names = _resolve_import_names(node, path, cwd)
            for dotted in names:
                if dotted in dormant_dotted:
                    if _line_has_waiver(source_lines, node.lineno):
                        continue
                    print(
                        f"{rel}:{node.lineno}: dormant import: {dotted} "
                        "(allow with '# allow-dormant-import: <reason>')",
                        file=sys.stderr,
                    )
                    failed = True
                    violation_count += 1
                    break  # one message per node

    if failed:
        print(f"\n{violation_count} dormant import(s) found.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
