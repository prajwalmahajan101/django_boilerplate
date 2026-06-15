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

## Step 7 — First CI run failed on apt pin staleness

- **P1.** First push of this PR (run 27555057537) failed at
  `make audit` with `E: Version '2.41-12+deb13u2' for 'libc6-dev'
  was not found`. Debian had rolled a security update
  (`+deb13u3`) and unpublished the older patch from the mirror.
  The pin worked locally because the user's Docker layer cache
  had `apt-get update` from before the rollover — CI starts cold
  and hits the live mirror.
- **Fix.** Re-ran the recapture command already documented in the
  Makefile comment block above `AUDIT_SYSTEM_DEPS:` and bumped
  pins: `libc6-dev` 2.41-12+deb13u2 → +deb13u3; `libpq-dev`
  17.9-0+deb13u1 → 17.10-0+deb13u1; `gcc` unchanged. Same SHA-pinned
  base image, so reproducibility is intact — only the upstream
  apt packages moved.
- **Follow-up for M2 or later.** This will keep happening on every
  Debian security update. Two non-mutually-exclusive options to log:
  (a) move to a Debian apt snapshot URL so the pin is immutable;
  (b) drop the patch suffix and accept "latest patch on Debian
  stable" as the reproducibility floor. Out of scope here — the
  one-line bump unblocks M1.

## Step 8 — Second CI run: the gate worked (11 CVEs caught)

- **PRAISE.** With apt pins fixed, `make audit` ran clean and
  surfaced 11 real CVEs the project was carrying: django 6.0.5
  (5 advisories — fix 6.0.6), tornado 6.5.5 (CVE-2026-49854,
  fix 6.5.6), idna 3.14 (CVE-2026-45409, fix 3.15), pyjwt 2.12.1
  (4 advisories — fix 2.13.0). Exactly the class of finding the M1
  plan exists to catch, and exactly the reason M1 had to run on
  every PR rather than being a manual `make audit` ritual.
- **Decision: fix in this PR, not a follow-up.** Once M1 merges,
  every subsequent PR will hit the same gate, so main would land
  with its own gate red. All four bumps are patch-level security
  upgrades within the existing `.in` ranges, so the fix is just
  re-running `pip-compile --upgrade-package` for each layer; no
  `.in` edits needed. SBOM regenerated; full test suite still 180
  passed.
- **Discovery: lockfile regeneration with `--strip-extras` warning.**
  pip-tools 7.5.3 warns that `--strip-extras` becomes default in
  8.0.0. Not blocking, but a flag to pin in the next `pip-tools`
  bump. Logged for M2.

## Exit

- Branch-protection rule pinned to the old job name
  (`ruff + django check + makemigrations + pytest (Python 3.12)`)
  needs re-pointing to the new name
  (`pre-commit + audit + sbom + pytest (Python 3.12)`) once CI is
  green. Flagged in the PR description.
- Follow-ups logged for M2: real Valkey service container +
  integration tests, `make deps-check` CI step, weekly
  `make audit-all` against every layered file, coverage floor.
