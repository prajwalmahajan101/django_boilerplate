# ADR-0005: Encode dormant-module policy with coverage + AST gates

- **Status:** Accepted
- **Date:** 2026-06-16
- **Deciders:** Prajwal Mahajan

## Context

Nine modules under `apps/core/` ship in-tree as fork-ready
utilities but have zero callers on the request path today:

- `core/utils/{s3,data,filters,valkey,ses,function_logger,aws,db}.py`
- `core/middleware/metrics_middleware.py`

Before M2 they dragged the coverage floor — a forker enabling one
of them would have inherited 0% coverage and no integration test.
Before M3 a contributor could silently re-activate one by adding
an import from live code, leaving the dormancy claim stale and
the request path untested.

The policy needs to (a) keep these modules in the tree for
downstream activation, (b) keep the coverage floor honest, and
(c) make silent re-activation impossible.

## Decision

We will enforce a two-halves contract:

1. **Coverage `omit`.** `.coveragerc [run] omit` lists every
   dormant module. The coverage gate (overall 80%, per-package
   80% as of M2.5) measures only live code.
2. **AST import gate.** `scripts/check_dormant_imports.py` walks
   every `.py` under `apps/` and `config/` at pre-commit time and
   fails the build if any `Import` / `ImportFrom` node resolves
   to a dormant module's dotted name. The dormant set is parsed
   from `.coveragerc` (single source of truth) and cross-checked
   against each file's module docstring for the literal marker
   `Dormant:` / `Dormant (transitively):`. A mismatch between the
   two halves exits 2 before the import walk.

The escape hatch is a same-line
`# allow-dormant-import: <reason>` comment on the import
statement (works across multi-line ruff-formatted imports —
the gate scans `lineno..end_lineno`). Reserve it for narrow seams
(atexit hooks, integration tests targeting the dormant module,
one-shot management commands), not for re-activating a module on
the request path. To activate properly: remove the `omit` entry,
remove the `Dormant:` marker, add the test row from
`docs/INDEX.md ## Dormant modules`.

Dormant→dormant imports (e.g. `s3.py` importing `aws.py`) are
exempt — they stay inside the dormancy boundary. Test files are
exempt — integration tests targeting a dormant module **are** the
documented activation step.

## Consequences

### Positive

- **Honest floor.** Coverage gate measures live code; dormant
  modules never inflate or deflate the number.
- **No silent activation.** A new `from core.utils.s3 import …`
  in a live module fails pre-commit with a path:line message and
  the escape-comment template — the contributor has to decide
  consciously whether they're activating the module or whether a
  waiver applies.
- **Single discoverable set.** The dormant set lives in one file
  (`.coveragerc`). Drift between that and the docstring markers
  is itself a gate failure.
- **Cross-project pattern.** `fastapi_boilerplate` carries the
  same dormant idea with `test_no_dormant_imports.py`; this ADR
  pins the Django port's specific shape.

### Negative

- **Activation requires two synced edits** (drop `omit`, drop
  docstring marker). Drift detection catches a half-done
  activation but the contributor sees a confusing exit-2 message
  before the helpful exit-1 import-walk message.
- **One extra pre-commit hook.** ~1s on a full-repo scan; cheap
  but real.
- **Ruff multi-line imports.** The gate has to scan
  `lineno..end_lineno` for the waiver because ruff-format expands
  `from x import (a, b)` across lines. Pinned in the gate's own
  unit tests (`tests/unit/test_check_dormant_imports.py`).

### Neutral

- **Marker syntax tolerates both forms.** `Dormant:` (the common
  case) and `Dormant (transitively):` (where the docstring
  qualifies that the only callers are themselves dormant) both
  satisfy the cross-check. The regex is
  `\bDormant\b[^:\n]*:`.
- **Atexit hook stays.** `apps/core/apps.py::CoreConfig.ready()`
  imports `dispose_all_engines` from dormant `core.utils.db`.
  This is documented in `db.py`'s docstring as the sole call
  site; the import carries
  `# allow-dormant-import: atexit cleanup hook` for the gate.

## Alternatives considered

- **Rely on code review only.** Pre-M2 reality — dormant modules
  silently joined the request path without integration tests
  multiple times. Rejected: review-only worked until it didn't.
- **Delete the dormant modules.** Loses the boilerplate's
  fork-ready story (the modules exist because downstream forks
  want a working starting point for S3 / SES / metrics /
  filters). Rejected: deletion would force every fork to
  re-implement, defeating the purpose of a boilerplate.
- **Move dormant modules into a separate package**
  (`django_boilerplate_extras` or similar). Loses the
  zero-friction activation story (`from core.utils.s3 import …`
  works the moment the policy lets it). Rejected as premature
  for nine files; revisit if the set crosses ~30.
- **Mark with a custom decorator instead of a docstring marker.**
  Decorators don't fire on bare-module imports, can't be checked
  statically without execution, and would require importing the
  marker from somewhere — adding a runtime dependency. Rejected:
  the docstring marker is plain text the AST gate can read
  without imports.

## References

- PR #16 — M3 dormant-import gate landing.
- [scripts/check_dormant_imports.py](../../scripts/check_dormant_imports.py)
- [docs/INDEX.md `## Dormant modules`](../INDEX.md) — the
  per-module activation table.
- [.coveragerc](../../.coveragerc) — the omit list (source of
  truth for the dormant set).
- [tests/unit/test_check_dormant_imports.py](../../tests/unit/test_check_dormant_imports.py)
  — pins the gate's behaviour.
- [ADR-0003](0003-ci-as-quality-gate.md) — CI runs this gate via
  the M1 pre-commit-in-CI wiring.
