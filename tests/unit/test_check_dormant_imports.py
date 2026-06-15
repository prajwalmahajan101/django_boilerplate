"""Unit tests for ``scripts/check_dormant_imports.py``.

The gate runs on every PR and is the only thing keeping the dormant
policy honest. A regression here would silently let a forker wire a
dormant utility back into the request path without an integration
test — exactly the M2 hazard the docstring callouts try to prevent.

Tests drive the script via ``subprocess`` against a fake source tree
under ``tmp_path`` (the script reads ``.coveragerc`` from ``cwd``).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_dormant_imports.py"


def _make_tree(
    tmp_path: Path,
    *,
    dormant_modules: dict[str, str] | None = None,
    live_modules: dict[str, str] | None = None,
    omit_overrides: list[str] | None = None,
    config_files: dict[str, str] | None = None,
) -> None:
    """Lay out a fake repo at ``tmp_path``.

    ``dormant_modules`` maps relative path -> file content; each path
    is added to ``.coveragerc`` omit unless ``omit_overrides`` is set.
    ``live_modules`` and ``config_files`` are written verbatim.
    """
    dormant_modules = dormant_modules or {}
    live_modules = live_modules or {}
    config_files = config_files or {}

    for rel, content in {**dormant_modules, **live_modules, **config_files}.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    omit_entries = omit_overrides if omit_overrides is not None else list(dormant_modules)
    omit_lines = "".join(f"    {entry}\n" for entry in omit_entries)
    (tmp_path / ".coveragerc").write_text(
        f"[run]\nsource = apps\nomit =\n{omit_lines}",
        encoding="utf-8",
    )


def _run(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


DORMANT_MODULE_BODY = '"""Dormant: ships in-tree for downstream forks; no live callers."""\n'


# ---------- clean tree ----------------------------------------------------


def test_clean_tree_exits_zero(tmp_path: Path):
    _make_tree(
        tmp_path,
        dormant_modules={"apps/core/utils/s3.py": DORMANT_MODULE_BODY},
        live_modules={"apps/core/services.py": '"""Live service."""\n'},
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


# ---------- violation paths ----------------------------------------------


def test_live_import_of_dormant_fails(tmp_path: Path):
    _make_tree(
        tmp_path,
        dormant_modules={"apps/core/utils/s3.py": DORMANT_MODULE_BODY},
        live_modules={
            "apps/core/services.py": ('"""Live service."""\nfrom core.utils.s3 import upload\n'),
        },
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "apps/core/services.py:2: dormant import: core.utils.s3" in result.stderr
    assert "1 dormant import(s) found." in result.stderr


def test_waiver_with_reason_suppresses(tmp_path: Path):
    _make_tree(
        tmp_path,
        dormant_modules={"apps/core/utils/s3.py": DORMANT_MODULE_BODY},
        live_modules={
            "apps/core/services.py": (
                '"""Live service."""\n'
                "from core.utils.s3 import upload  # allow-dormant-import: probe\n"
            ),
        },
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr


def test_waiver_without_reason_still_fails(tmp_path: Path):
    _make_tree(
        tmp_path,
        dormant_modules={"apps/core/utils/s3.py": DORMANT_MODULE_BODY},
        live_modules={
            "apps/core/services.py": (
                '"""Live service."""\n'
                "from core.utils.s3 import upload  # allow-dormant-import:\n"
            ),
        },
    )
    result = _run(tmp_path)
    assert result.returncode == 1


# ---------- skip-self / test-file exemptions ------------------------------


def test_dormant_to_dormant_import_is_allowed(tmp_path: Path):
    _make_tree(
        tmp_path,
        dormant_modules={
            "apps/core/utils/aws.py": DORMANT_MODULE_BODY,
            "apps/core/utils/s3.py": (
                '"""Dormant: ships in-tree for downstream forks."""\n'
                "from core.utils.aws import get_client\n"
            ),
        },
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr


def test_test_file_importing_dormant_is_allowed(tmp_path: Path):
    _make_tree(
        tmp_path,
        dormant_modules={"apps/core/utils/ses.py": DORMANT_MODULE_BODY},
        live_modules={
            "apps/core/tests/test_ses.py": (
                '"""Integration test for dormant ses."""\n'
                "from core.utils.ses import send_email\n"
            ),
        },
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr


# ---------- ImportFrom forms ---------------------------------------------


def test_from_package_import_dormant_submodule_fails(tmp_path: Path):
    _make_tree(
        tmp_path,
        dormant_modules={"apps/core/utils/s3.py": DORMANT_MODULE_BODY},
        live_modules={
            "apps/core/services.py": ('"""Live service."""\nfrom core.utils import s3\n'),
        },
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "core.utils.s3" in result.stderr


# ---------- drift detection ----------------------------------------------


def test_omitted_path_without_docstring_marker_is_drift(tmp_path: Path):
    _make_tree(
        tmp_path,
        dormant_modules={
            "apps/core/utils/s3.py": '"""Plain docstring — no marker."""\n',
        },
    )
    result = _run(tmp_path)
    assert result.returncode == 2
    assert "dormant-set drift" in result.stderr
    assert "missing 'Dormant:' module-docstring marker" in result.stderr


def test_marker_without_omit_entry_is_drift(tmp_path: Path):
    _make_tree(
        tmp_path,
        dormant_modules={"apps/core/utils/s3.py": DORMANT_MODULE_BODY},
        omit_overrides=[],  # docstring marker present but not omitted
    )
    result = _run(tmp_path)
    assert result.returncode == 2
    assert "dormant-set drift" in result.stderr
    assert "not in .coveragerc" in result.stderr


def test_transitive_marker_form_accepted(tmp_path: Path):
    """``Dormant (transitively):`` must also satisfy the marker check."""
    _make_tree(
        tmp_path,
        dormant_modules={
            "apps/core/utils/aws.py": (
                '"""Dormant (transitively): only dormant callers as of M2."""\n'
            ),
        },
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
