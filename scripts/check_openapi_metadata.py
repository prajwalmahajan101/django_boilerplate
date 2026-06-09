#!/usr/bin/env python3
"""Fail when any DRF view is missing OpenAPI metadata for drf-spectacular.

The repo invariant (``apps/core/CLAUDE.md``, response-envelope contract):
every public view must publish a documented schema so the OpenAPI
contract stays accurate as the surface grows. Concretely, this script
AST-walks every ``apps/**/views.py`` and rejects:

* A function-based ``@api_view([...])`` route that does NOT also have a
  paired ``@extend_schema(...)`` decorator. Without the
  ``@extend_schema`` decoration drf-spectacular generates a generic
  ``object`` for ``data`` and omits the standard 4xx/5xx error
  responses.
* A class-based DRF view (``GenericAPIView`` /
  ``ViewSet`` / ``APIView`` subclass) that declares neither
  ``serializer_class = ...`` nor at least one ``@extend_schema(...)``
  decoration on a verb method. The serializer is what drives the
  typed-envelope shape in the schema.

This script does not boot Django (stays fast for CI). It is intended
to catch silent contract regressions when a new view ships without a
matching ``@extend_schema`` block.

Exit codes:
    ``0`` — every view declares either ``serializer_class`` or
            ``@extend_schema``.
    ``1`` — one or more views are missing the required metadata.

Run manually via::

    python scripts/check_openapi_metadata.py

Wire as a pre-commit hook so new views can't ship without a schema.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPS_ROOT = ROOT / "apps"

# Class names that are CBVs whose subclasses must declare schema. The
# list is intentionally narrow; expand when new bases are introduced.
CBV_BASE_NAMES = {
    "APIView",
    "GenericAPIView",
    "ViewSet",
    "GenericViewSet",
    "ModelViewSet",
    "ReadOnlyModelViewSet",
    "ListAPIView",
    "RetrieveAPIView",
    "CreateAPIView",
    "UpdateAPIView",
    "DestroyAPIView",
    "ListCreateAPIView",
    "RetrieveUpdateAPIView",
    "RetrieveDestroyAPIView",
    "RetrieveUpdateDestroyAPIView",
    "SocialLoginView",
}

VERB_METHODS = {
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "options",
    "list",
    "retrieve",
    "create",
    "update",
    "partial_update",
    "destroy",
}


def _decorator_name(d: ast.expr) -> str | None:
    if isinstance(d, ast.Call):
        d = d.func
    if isinstance(d, ast.Name):
        return d.id
    if isinstance(d, ast.Attribute):
        return d.attr
    return None


def _has_extend_schema(decorators: list[ast.expr]) -> bool:
    """Accept either bare ``@extend_schema`` or a project-convention alias.

    Pre-built schema decorators in this repo live under
    ``apps/<app>/api_schemas/`` with the ``*_schema`` suffix (e.g.
    ``api_key_delete_schema = extend_schema(...)``). They are
    indistinguishable from a direct ``@extend_schema`` at call site
    semantically; recognise the suffix so the guard does not chase
    these aliases.
    """
    for d in decorators:
        name = _decorator_name(d)
        if name == "extend_schema" or (name and name.endswith("_schema")):
            return True
    return False


def _is_api_view(decorators: list[ast.expr]) -> bool:
    return any(_decorator_name(d) == "api_view" for d in decorators)


def _class_violations(node: ast.ClassDef) -> list[tuple[int, str, str]]:
    """Return violations for a class definition."""
    base_names = {b.id for b in node.bases if isinstance(b, ast.Name)} | {
        b.attr for b in node.bases if isinstance(b, ast.Attribute)
    }
    if not (base_names & CBV_BASE_NAMES):
        return []

    has_serializer = any(
        isinstance(stmt, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "serializer_class" for t in stmt.targets)
        for stmt in node.body
    )
    has_schema_on_class = _has_extend_schema(node.decorator_list)
    if has_serializer or has_schema_on_class:
        return []
    has_schema_on_verb = any(
        isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef)
        and stmt.name in VERB_METHODS
        and _has_extend_schema(stmt.decorator_list)
        for stmt in node.body
    )
    if has_schema_on_verb:
        return []
    return [(node.lineno, node.name, "serializer_class or @extend_schema")]


def _func_violations(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[int, str, str]]:
    """Return violations for an @api_view function-based route."""
    if not _is_api_view(node.decorator_list):
        return []
    if _has_extend_schema(node.decorator_list):
        return []
    return [(node.lineno, node.name, "@extend_schema")]


def _violations(path: Path) -> list[tuple[int, str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: list[tuple[int, str, str]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            out.extend(_class_violations(node))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            out.extend(_func_violations(node))
    return out


def main() -> int:
    failed = False
    for path in sorted(APPS_ROOT.rglob("views.py")):
        # Skip core's view module — health / metrics / csp-report
        # endpoints have their own minimal schema decorators applied
        # via core.api_schemas and don't follow the public-surface
        # contract this guard enforces.
        if path.parent.name == "core":
            continue
        for lineno, name, missing in _violations(path):
            rel = path.relative_to(ROOT)
            print(f"{rel}:{lineno}: {name}: missing {missing}")
            failed = True
    if failed:
        print(
            "\nEvery DRF view under apps/<app>/views.py must publish an "
            "OpenAPI schema for drf-spectacular:\n"
            "  - Class-based views: set serializer_class = <Serializer> "
            "or decorate a verb method with @extend_schema(...).\n"
            "  - @api_view functions: pair with @extend_schema(...).\n"
            "Without this drf-spectacular emits a generic `object` for "
            "data and omits the standard error envelope responses.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
