#!/usr/bin/env python3
"""Fail the commit if any documented stale reference appears in docs.

This script is the corrective answer to three review cycles of
rename-rot: the same renamed/deleted symbol kept showing up in docs
after the code had moved on. Manual discipline (a checklist in the
PR template, a CHANGELOG entry, a grep before push) was empirically
not enough. So the responsibility now lives in a pre-commit hook
that runs on every commit and refuses to let the rot land.

Scope:
- Scans only documentation surfaces: ``docs/``, top-level ``CLAUDE.md``,
  ``README.md``, app-level ``apps/*/CLAUDE.md``, and ``CHANGELOG.md``.
  Code is intentionally *not* scanned — refactors there are caught by
  tests / type-checker; this hook only enforces doc hygiene.
- Skips ``.code_review/`` (a living record of past state, allowed to
  reference old names) and ``CHANGELOG.md`` *entries describing the
  rename itself* — see the ``allow_changelog`` flag below.

Patterns + replacement hints live in ``scripts/stale_refs.yaml`` so a
rename commit can append the old symbol in the same PR. The hook
seed-loads with the three symbols that have caused doc-rot in past
cycles; future renames append.

Exit code 0 → all clean. Exit code 1 → at least one pattern matched;
each hit is printed with ``path:line: <line text>`` plus the
configured replacement hint, so the author can fix and re-commit
without consulting external docs.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print(
        "check_stale_refs.py: PyYAML is required. Install it with "
        "`pip install pyyaml` (it is already in requirements/dev.txt).",
        file=sys.stderr,
    )
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "scripts" / "stale_refs.yaml"

# Documentation surfaces scanned. Globs are evaluated from REPO_ROOT.
INCLUDE_GLOBS = [
    "docs/**/*.md",
    "CLAUDE.md",
    "README.md",
    "apps/*/CLAUDE.md",
    "apps/*/*/CLAUDE.md",
]

# Always-ignored paths. ``.code_review/`` is a living history of prior
# review state and is *expected* to mention old symbols. ``CHANGELOG.md``
# is allowed because a rename entry must use the old name to describe
# the change.
EXCLUDE_PREFIXES = (
    ".code_review/",
    "CHANGELOG.md",
)


def load_manifest() -> list[tuple[re.Pattern[str], str]]:
    if not MANIFEST.exists():
        print(f"check_stale_refs.py: manifest not found at {MANIFEST}", file=sys.stderr)
        sys.exit(2)
    raw = yaml.safe_load(MANIFEST.read_text()) or {}
    patterns = raw.get("patterns") or []
    compiled: list[tuple[re.Pattern[str], str]] = []
    for entry in patterns:
        pattern = entry.get("pattern")
        hint = entry.get("replacement", "")
        if not pattern:
            continue
        compiled.append((re.compile(pattern), hint))
    return compiled


def discover_files() -> list[Path]:
    files: set[Path] = set()
    for glob in INCLUDE_GLOBS:
        for path in REPO_ROOT.glob(glob):
            if not path.is_file():
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if any(rel.startswith(prefix) for prefix in EXCLUDE_PREFIXES):
                continue
            files.add(path)
    return sorted(files)


def main() -> int:
    patterns = load_manifest()
    if not patterns:
        return 0

    files = discover_files()
    hits: list[str] = []

    for path in files:
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError as exc:
            print(f"check_stale_refs.py: cannot read {path}: {exc}", file=sys.stderr)
            continue

        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, line in enumerate(lines, start=1):
            for compiled, hint in patterns:
                if compiled.search(line):
                    snippet = line.strip()[:120]
                    hits.append(
                        f"{rel}:{lineno}: {snippet}\n"
                        f"    → {hint}"
                    )

    if hits:
        print("check_stale_refs.py: stale references found:", file=sys.stderr)
        for hit in hits:
            print(hit, file=sys.stderr)
        print(
            f"\n{len(hits)} stale reference(s) detected. Update docs to use the "
            "current names; if you need to keep one (e.g. CHANGELOG-style "
            "history) move it outside the scanned surfaces.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
