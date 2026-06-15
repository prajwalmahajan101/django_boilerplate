# M2 — Coverage gates notes

> Live log captured **while** tightening the coverage gate and
> closing the M1 deferrals. Companion to
> [`docs/v1.0.0-roadmap.md`](v1.0.0-roadmap.md) § M2 and
> [ADR-0003](decisions/0003-ci-as-quality-gate.md) ("CI is the
> production quality gate").

## Legend

- **P0** — blocks the M2 exit criteria.
- **P1** — usable workaround exists; needs a fix-up.
- **P2** — polish / nice-to-have, not 1.0-blocking.
- **PRAISE** — primitive that paid off without modification.

---

## Step 1 — Dormant triage expanded mid-execution

- **PRAISE.** The plan started with 6 dormant candidates (s3, data,
  filters, valkey, ses, function_logger). `grep -rn` across `apps/`
  and `config/` confirmed all six had zero in-tree callers, plus
  surfaced two more:
  - `utils/aws.py` — the only callers (`utils/s3.py`,
    `utils/ses.py`) are themselves dormant. Transitively dormant.
  - `middleware/metrics_middleware.py` — `apps/core/CLAUDE.md`
    already calls it out as "NOT wired today; activation is a
    single `MIDDLEWARE` edit". So the docstring honesty was already
    there; the omit policy just makes it count for the gate too.
- **Discovery during Step M2.4 (`utils/db.py` tests).** Planned to
  write tests, then found every public symbol except
  `dispose_all_engines` (an atexit hook in `apps/core/apps.py`) has
  zero in-tree callers. Pivoted to "mark dormant" — saves the test
  work and keeps the policy honest. Final dormant set: 9 modules.

## Step 2 — Dormant docstrings + `.coveragerc` omit

- One callout per module, identical prose. Pattern matches what
  `apps/core/CLAUDE.md` already documents; the omit-list lives in
  `.coveragerc [run] omit`. Effect on the gate: omitted modules
  don't count against the floor, but every other coverage signal
  (test discovery, missing-line report) still works.
- **Baseline shift.** Overall coverage 64.03% (including dormant)
  → 68.42% (dormant omitted). The floor was set at 70 the whole
  time, so this surfaces just how much the dormant modules had
  been dragging the picture.

## Step 3 — Tests for the request-path set

Five atomic commits, one per group. Per-module coverage:

| Module                              | Before | After  | Tests added                                          |
| ----------------------------------- | ------ | ------ | ---------------------------------------------------- |
| `core/permissions.py`               | 15%    | 100%   | 6 (HasResourcePermission) + 5 (user_has_permission)  |
| `core/rbac_registry.py`             | 62%    | 100%   | 6 (register/lookup/collision/isolation)              |
| `core/registries/__init__.py`       | 0%     | 100%   | 1 (re-export identity)                               |
| `core/responses/paginated.py`       | 26%    | 100%   | 11 (Page branch, manual branch, edge cases)          |
| `core/views.py`                     | 39%    | 97%    | 24 (health/readiness/csp/metrics + _ip_allowed)      |
| `accounts/permissions.py`           | 0%     | 100%   | 3 (anonymous, with-role, without-role)               |

- **PRAISE.** `force_authenticate(request, user=...)` from
  `rest_framework.test` was the right tool for the privileged-view
  tests. First pass set `request.user = _privileged_user()` on the
  raw WSGI request, but `@api_view` re-runs authentication and
  overwrites it with `AnonymousUser`. `force_authenticate` plants
  the user where the DRF Request constructor will find it.
- **P2.** The two remaining uncovered lines in `core/views.py` are
  the prometheus_client happy path (lines 162-173). Will close once
  prometheus-client lands in `requirements/prod.in`; not worth
  hand-rolling an import-shim test for the dormant flag.

## Step 4 — Coverage floor: 75% (honest), not 85% (aspirational)

- **Decision.** Measured overall at 75.24% after Step 3. Set
  `.coveragerc fail_under = 75`. Mirrors FastAPI 1.0's stance
  ("ship the gate honest even when red"); the ratchet plan to 85%
  is documented in the CHANGELOG, not deferred to vibes.
- **Per-package floors.** Measured:
  - `apps/core/` 79.26% → floor 75% (room to grow without slipping).
  - `apps/accounts/` 61.17% → floor 60% (gap is `accounts/
    {adapters,backends,views,serializers}.py` at 0–60%, all
    request-path but accounts-app scope — deferred to a focused
    follow-up PR rather than inflating M2's diff).

## Step 5 — `make test-cov` wired into CI

- Single-line swap: the existing "Pytest — e2e + default suite"
  step (`make test`) became "Pytest — full suite + coverage gate"
  (`make test-cov`). Unit + integration steps stay separate above
  it for fast feedback. The duplicated work (unit/integration ran
  twice) is ~30s and the failure-ordering value is worth more.

## Step 6 — Valkey container + real-backend integration test

- **PRAISE.** `tests/integration/test_valkey_roundtrip.py` opts in
  via `VALKEY_AVAILABLE=1` and skips cleanly otherwise — so local
  `make test` stays offline (LocMemCache), and CI sets the flag +
  provisions `valkey/valkey:7` alongside postgres.
- **P1 — Django 6 `CacheHandler` internal API rename.** First fixture
  draft reset cache memoisation by poking
  `caches._caches.caches = {}`. That attribute moved in Django 6.
  Fix: just rely on `override_settings(CACHES=...)` — Django fires
  `setting_changed` signals that the framework's own
  `clear_cache_handlers` listener catches. No private-API poking
  needed; the comment in the fixture explains the contract for the
  next contributor who's tempted to "be helpful".

## Step 7 — `make deps-check` deferred, not landed

- **P1 — `deps-check` is nondeterministic.** The plan called for a
  CI step running `make deps-check`. Local test of the gate showed
  back-to-back docker runs of `pip-compile` against the same
  `requirements/*.in` files produce **different transitive
  versions**: PyPI's index mirror serves stale metadata at minute
  granularity (`boto3` 1.43.6 vs 1.43.29, `certifi` 2026.4.22 vs
  2026.5.20, `click` 8.3.3 vs 8.4.1 all seen in adjacent runs).
  A flaky gate isn't a gate.
- **Decision.** Drop the CI step. Pre-commit's
  `pip-compile-base` / `pip-compile-dev` hooks still catch drift
  on contributor commits (and CI still `SKIP=`s them for the same
  PyPI-flakiness reason). Logged for a later phase: either
  (a) pin to a frozen PyPI snapshot URL via `--index-url`, or
  (b) rework the check to compare hash-only against the committed
  lockfile rather than regenerating it from scratch.

## Step 8 — Roadmap update: M3 scope shrunk

- **Discovery from M1 carried into M2.** Five of the six AST gates
  M3 originally promised (`check_dead_utils`, `check_layering`,
  `check_thread_safety`, `check_openapi_metadata`,
  `check_stale_refs`) already shipped in M1 — they were in
  `.pre-commit-config.yaml` and M1 wired pre-commit into CI.
  M3's remaining net-new is just the dormant-module AST gate
  (M2 added the *docstring* callouts; M3 adds the import-time
  enforcement). `docs/v1.0.0-roadmap.md` § M3 updated to reflect
  this.

## Exit

- 60 new tests; +5,500 LOC mostly in test files. Final local
  numbers — overall 75.24%, core 79.26%, accounts 61.17%, all three
  gates green.
- Follow-ups logged:
  - `accounts/{adapters,backends,views,serializers}.py` coverage —
    focused PR.
  - prometheus_client happy path in `core/views.py` — covered when
    activation lands.
  - `make deps-check` CI integration — needs deterministic PyPI
    source first.
  - M3 dormant-import AST gate.
