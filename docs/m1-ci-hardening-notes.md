# M1 — CI hardening notes

> Live log captured **while** wiring local quality gates into
> `.github/workflows/test.yml`. Companion to
> [ADR-0003](decisions/0003-ci-as-quality-gate.md) and
> [`docs/v1.0.0-roadmap.md`](v1.0.0-roadmap.md) § M1.

## Legend

- **P0** — blocks the M1 exit criteria (CI green with all gates).
- **P1** — usable workaround exists; needs a fix-up PR.
- **P2** — polish / nice-to-have, not 1.0-blocking.
- **PRAISE** — primitive that paid off without modification.

---

## Step 1 — Valkey service container *(deferred to M2)*

- **P2 → deferred.** The roadmap called for a `valkey/valkey:7`
  service container so integration tests could exercise the real
  cache + rate-limit + circuit-breaker backends. Reading
  `config/settings/test.py` showed test settings hard-code
  `LocMemCache` for both `default` and `rate_limit`, plus
  `CELERY_BROKER_URL = "memory://"`. `grep -rn "valkey\|VALKEY" tests/`
  returned nothing — no test actually hits Valkey today.
- **Decision.** Don't add a Valkey service container in M1; it would
  be dead config that future contributors would have to reason
  about. Defer to M2, which is the phase that adds the
  integration-tier tests that *would* exercise the real cache.
- **Action item for M2.** When M2 adds those tests, the service
  container, env vars, and a small `config/settings/ci.py` (or test
  override) that points caches at `127.0.0.1:6379` all land
  together — one coherent change instead of scaffolding-now,
  consumers-later.

## Step 2 — Split pytest into unit / integration / e2e

- **PRAISE.** `Makefile` already had `test-unit`, `test-integration`,
  and `test` as separate targets keyed on pytest markers. The CI
  change is one block: replace the single `make test` step with
  three steps invoking the existing targets in order
  (unit → integration → e2e + default).
- **Trade-off.** `make test` already runs unit + integration + e2e
  together (it's `pytest -m "not slow and not external"`), so the
  third step re-runs the first two. Accepted: the duplicate run is
  ~30s and the value is that a flaky e2e doesn't blur a unit
  regression — unit failures surface first because they're fastest.
  If runtime becomes a concern, future work can narrow the third
  step to `-m e2e`.

## Step 3 — pre-commit step

- **PRAISE.** `.pre-commit-config.yaml` already wires ruff (lint +
  format), pydocstyle, darglint, and five repo-local AST guards
  (`check_dead_utils`, `check_layering`, `check_thread_safety`,
  `check_openapi_metadata`, `check_stale_refs`). One `pre-commit
  run --all-files` step replaces both the two existing `ruff` steps
  and pulls in five guards CI never ran before. Discovery: this
  collapses most of the work the roadmap had earmarked for M3 (AST
  / policy gates) — only the *dormant-module* policy + test remain
  as net-new for M3.
- **P1 — pip-compile hooks need a network skip.** The two `local`
  hooks `pip-compile-base` / `pip-compile-dev` shell out to PyPI
  to regenerate `requirements/*.txt`. On a fresh CI checkout where
  `requirements/*.in` is "changed" relative to git's empty cache,
  these hooks run and either (a) succeed by hitting PyPI, which is
  a flake risk and a non-determinism source, or (b) drift the
  lockfile from what's committed. Workaround: `SKIP=pip-compile-base,
  pip-compile-dev` env on the CI step. Lockfile drift is still
  caught locally on every contributor's pre-commit; closing the
  CI-side gap is a one-line `make deps-check` step in M2.

## Step 4 — pip-audit (`make audit`)

- **PRAISE.** `make audit` already runs pip-audit inside an
  ephemeral Docker container against `requirements/prod.txt`, so
  the CI step is a single line and inherits the local definition
  verbatim — no version drift between local and CI.
- **Neutral.** Docker pull adds ~30–45s on cold cache; acceptable
  given the bound is what blocks merging a vulnerable dep.

## Step 5 — SBOM drift check (`make sbom-diff`)

- **PRAISE.** Same pattern as audit — Make target already exists,
  regenerates a fresh CycloneDX SBOM in a container and diffs it
  against the committed `sbom/prod-sbom.json`. CI step is one line.
- **P2.** A dep bump landing without `make sbom` will fail this gate
  loudly, which is the desired behaviour. Worth a line in
  `docs/dependency-management.md` once M4's docs sweep lands.

## Step 6 — Discovery: M3 is mostly already done

- The five AST guards the roadmap M3 promised
  (`check_stale_refs.py`, `check_dead_utils.py`, plus three more) are
  already in `.pre-commit-config.yaml` and now also run in CI as of
  this PR. M3's remaining net-new scope is just the dormant-module
  policy + the matching AST gate. Will update the roadmap as part
  of M4's docs sweep — out of scope for M1.

## Exit

- Branch-protection rule pinned to the old job name
  (`ruff + django check + makemigrations + pytest (Python 3.12)`)
  needs re-pointing to the new name
  (`pre-commit + audit + sbom + pytest (Python 3.12)`) once CI is
  green. Flagged in the PR description.
- Follow-ups logged for M2: real Valkey service container +
  integration tests, `make deps-check` CI step, weekly
  `make audit-all` against every layered file, coverage floor.
