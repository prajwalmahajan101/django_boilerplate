# ADR-0003: Treat CI as the production quality gate

- **Status:** Accepted
- **Date:** 2026-06-15
- **Deciders:** Prajwal Mahajan

## Context

Until M1 of the v1.0.0 roadmap, the local quality bar was strictly
higher than the CI quality bar:

- `.pre-commit-config.yaml` runs ruff (lint + format), pydocstyle,
  darglint, and five repo-local AST guards
  (`check_dead_utils.py`, `check_layering.py`,
  `check_thread_safety.py`, `check_openapi_metadata.py`,
  `check_stale_refs.py`).
- `Makefile` exposes `make audit` (pip-audit against
  `requirements/prod.txt`), `make sbom-diff` (CycloneDX drift),
  `make deps-check` (lockfile vs `.in` drift), and split test
  targets (`test-unit`, `test-integration`, `test`).
- `.github/workflows/test.yml` only ran ruff + `manage.py check` +
  `makemigrations --check` + a single `make test` step against a
  Postgres service container. None of the AST guards, none of the
  audit/SBOM gates, and no test-tier split.

Four merges landed in the 24h before this ADR (#known-issues-p4,
#pytest-in-dev, #nginx, #lint-debt-burndown) where the local pre-commit
bar would have caught a regression that CI alone would have missed.
The asymmetry is silently load-bearing: it survives only as long as
every contributor remembers to run `pre-commit` and the
`make audit/sbom` targets locally. The next contributor — or any
fork — lowers the bar by default.

## Decision

Every check that lives in `Makefile` or `.pre-commit-config.yaml` and
is meant to block bad code MUST also run in
`.github/workflows/test.yml` on every PR to `main`. The
Makefile / pre-commit definitions are the single source of truth; the
workflow is the wrapper that invokes them. Adding a new gate is
therefore a two-step task: add the Make target or pre-commit hook,
then wire it into the workflow.

## Consequences

### Positive

- Local and CI signals converge: a green pre-commit + `make audit
  sbom-diff test` locally is sufficient evidence that CI will pass.
- Forks inherit the gate automatically — no out-of-band runbook for
  "things you must run before pushing".
- Audit / SBOM regressions are caught at PR review time, not on the
  next dependency bump or production deploy.

### Negative

- CI runtime grows from ~1m to an expected ~3–5m (pre-commit ~30s,
  audit ~45s under Docker pull, sbom-diff ~30s, integration tier
  adds ~30s).
- Two pre-commit hooks (`pip-compile-base`, `pip-compile-dev`) shell
  out to PyPI to regenerate lockfiles and are skipped via `SKIP=` in
  CI. Lockfile drift is still caught locally by the same hooks on
  the contributor's pre-commit run, and a future CI step
  (`make deps-check`) will close the gap from the CI side — tracked
  in v1.0.0 roadmap M2.

### Neutral

- The workflow's `name:` is now `pre-commit + audit + sbom + pytest`
  rather than `ruff + django check + makemigrations + pytest`,
  reflecting the broader scope. Branch-protection rules pinned to
  the old name need to be re-pinned.

## Alternatives considered

- **Keep CI thin, trust local discipline.** Rejected. Already the
  status quo and already failing: four recent merges proved local
  discipline alone doesn't survive multiple contributors or forks.
- **Replace `Makefile` with composite GitHub Actions.** Rejected.
  Breaks the "runnable locally without GitHub" property. The Makefile
  works on a laptop, in a container, and on any CI provider; the
  workflow is intentionally a thin wrapper.
- **Defer audit/SBOM to a separate nightly workflow.** Rejected for
  on-PR gates because a vulnerable dep should block the PR that
  introduces it, not surface 24h later. A weekly `audit-all` against
  every layered file is still a good idea and is logged as a follow-up
  in v1.0.0 roadmap M2.

## References

- [v1.0.0 roadmap](../v1.0.0-roadmap.md) § M1.
- [M1 phase journal](../m1-ci-hardening-notes.md).
- `.github/workflows/test.yml`, `.pre-commit-config.yaml`, `Makefile`.
