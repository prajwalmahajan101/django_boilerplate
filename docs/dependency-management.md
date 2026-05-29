# Dependency management

Lock discipline is layered, scanners are pinned, the supply-chain graph is an artefact under version control. This doc is the canonical reference for how Python dependencies are managed in this repository.

> **Commands cheat sheet:** [../README.md](../README.md#commands) · **Conventions:** [../CLAUDE.md](../CLAUDE.md)

## Lock layers

`requirements/` has four layers compiled with `pip-compile --generate-hashes` from `.in` sources into `.txt` lockfiles:

| Layer | Source | Lockfile | Purpose |
|---|---|---|---|
| **base** | `requirements/base.in` | `base.txt` | Runtime dependencies shared by dev + prod + test. |
| **prod** | `requirements/prod.in` | `prod.txt` | Production-only additions on top of `base`. Installed by the runtime Docker image. |
| **dev** | `requirements/dev.in` | `dev.txt` | Local-dev tooling (`pip-tools`, `ipython`, `django-debug-toolbar`, `pip-audit`, `cyclonedx-bom`, `psycopg2-binary`). |
| **test** | `requirements/test.in` | `test.txt` | Test-only tooling (`pytest`, `pytest-django`, `pytest-cov`, `factory-boy`). |

The Dockerfile takes `REQUIREMENTS_FILE` as a build arg (defaults to `requirements/prod.txt`) and enforces `pip install --require-hashes`. Any wheel whose sha256 doesn't match the pinned hash fails the build — the supply-chain boundary is at image-build time.

## Pinning discipline

### Top-level bounds

Every entry in `*.in` carries an upper bound matching the `>=X.Y,<X+1` pattern (SemVer-major constraint). Example from `requirements/base.in`:

```
django>=6.0,<6.1
djangorestframework>=3.17,<3.18
celery>=5.4,<6.0
```

No unbounded entries. Unbounded `.in` entries are a policy violation — silent major bumps are the exact failure mode the bounds prevent.

### Hashes

`pip-compile --generate-hashes` emits sha256 hashes for every wheel. The lockfile header records the invocation used; keep it consistent across regenerates so diffs are clean.

### `--allow-unsafe` (dev layer only)

`dev.in` transitively pulls `pip-tools`, which depends on `pip` and `setuptools`. Without `--allow-unsafe`, `pip-compile` refuses to pin these two, and a subsequent `--require-hashes` install fails with `setuptools not pinned`. The dev lockfile is therefore regenerated with `--allow-unsafe`; the other three layers are regenerated without it.

### apt packages

Debian packages installed in `Dockerfile` and `Makefile:AUDIT_SYSTEM_DEPS` are pinned to exact versions captured via `apt-cache policy` inside the digest-pinned `python:3.12-slim` image. This is the only reproducibility gap `--require-hashes` does not cover — without the pins, the same `Dockerfile` builds against whichever Debian snapshot is current at build time.

The security-epoch suffix `+deb13uN` rotates when Debian ships a point-release. Recapture the versions when that happens, **not** on a calendar.

## Refresh calendar

| What | When | How |
|---|---|---|
| `make audit-all` (vuln scan) | **Monthly** | Ad-hoc. If pip-audit flags a CVE the team chooses not to fix, record it in `.pip-audit.toml`. |
| `pip-compile` refresh (all four layers) | **Quarterly** | Regenerate each `.txt` from its `.in`; commit hashes with the `.in` edits. |
| Base-image digest refresh | **Quarterly** | `docker pull python:3.12-slim` → recapture sha256 digest in `Dockerfile:6`, `Dockerfile:36`, `Makefile:PYTHON_IMAGE`, and both `docker-compose*.yml` files. |
| apt version pins | **On Debian point-release** | `apt-cache policy gcc libc6-dev libpq-dev libpq5 postgresql-client` inside the current digest-pinned image. |

## When adding a new dependency

1. **Choose the layer.** Runtime code imports it → `base.in`. Local-dev tooling → `dev.in`. Test-only → `test.in`. Production-only (rare) → `prod.in`.
2. **Bound it.** `>=X.Y,<X+1`. No exceptions.
3. **Regenerate the `.txt`.**
   ```bash
   # All from the project root; run inside the digest-pinned image for deterministic hashes
   pip-compile --generate-hashes               --output-file=requirements/base.txt requirements/base.in
   pip-compile --generate-hashes --allow-unsafe --output-file=requirements/dev.txt  requirements/dev.in
   pip-compile --generate-hashes               --output-file=requirements/prod.txt requirements/prod.in
   pip-compile --generate-hashes               --output-file=requirements/test.txt requirements/test.in
   ```
4. **Validate locally.**
   ```bash
   make check        # pip check — detects transitive conflicts
   make deps-check   # verifies each .txt is in sync with its .in
   make audit        # pip-audit against prod.txt
   ```
5. **Refresh the SBOM** if this affected `prod.txt`:
   ```bash
   make sbom         # writes sbom/prod-sbom.json
   ```
   Commit the updated `sbom/prod-sbom.json` alongside the dep change.

## Makefile targets

All targets run inside the digest-pinned `python:3.12-slim` image (`Makefile:PYTHON_IMAGE`) — no state leaks onto the host.

| Target | Purpose |
|---|---|
| `make audit` | `pip-audit` against `requirements/prod.txt`. Pinned version: `Makefile:PIP_AUDIT_VERSION`. |
| `make audit-all` | `pip-audit` against every layered requirements file. Failure on any layer is non-blocking (prints, continues). |
| `make check` | `pip install --require-hashes -r prod.txt` + `pip check`. Surfaces transitive version conflicts. |
| `make deps-check` | Regenerates each `.txt` in-memory from its `.in` and diffs. Non-zero exit on drift. Run before commits that touch `requirements/`. Also fired automatically by the pre-push hook (see below). |
| `make sbom` | Writes `sbom/prod-sbom.json` (CycloneDX 1.6) from `prod.txt`. Pinned tool version: `Makefile:CYCLONEDX_VERSION`. |
| `make sbom-diff` | Regenerates the SBOM into a temp file and diffs the `(name, version, purl)` component set against the committed `sbom/prod-sbom.json`. Non-zero exit on drift. Catches transitive additions in PRs that don't touch `.in` files (e.g. a transitive dep silently appears after a hash refresh). |
| `make install-hooks` | Symlinks `scripts/git-hooks/*` into `.git/hooks/` (idempotent). One-time setup per checkout — `.git/hooks/` is not under VCS, so the symlinks have to be re-installed when a new clone is made. |

## Pre-push gate

`scripts/git-hooks/pre-push` runs `make deps-check` automatically when a pushed commit changes `requirements/*.in`, `requirements/*.txt`, or `Makefile`. Any other push is a no-op. Install once per checkout:

```bash
make install-hooks
```

The hook is the cheapest pre-merge gate that catches the failure mode bounded `.in` discipline relies on: `.in` edited without regenerating its `.txt`. It does **not** replace human review, and it does not run on every commit — only at push time. Bypass for emergencies with `git push --no-verify`; the bypass should be paired with a follow-up `chore(deps):` commit that fixes the drift.

The full check builds four ephemeral docker containers and runs `pip-compile` four times, so it adds ~60s to a relevant push. Most pushes don't touch dependency inputs and pay nothing.

## Vulnerability acceptance

When `pip-audit` flags a CVE the team decides not to fix — transitive impact is low, upstream hasn't patched, a mitigating control exists — record it in `.pip-audit.toml` at the repo root. The file is a **governance artefact**: `make audit` does not automatically honour it. Its purpose is to force "we decided not to fix" into tracked, reviewable form.

Schema (one table per accepted CVE):

```toml
[[accepted]]
id       = "CVE-2025-XXXXX"           # CVE or GHSA ID
package  = "<pip-package-name>"       # The vulnerable dependency
reason   = "<one-line rationale>"     # Why we're not fixing now
expiry   = "YYYY-MM-DD"               # Re-evaluate by this date
owner    = "<name/role>"              # Who owns the decision
```

Re-evaluate entries whose expiry has passed during the monthly scan. Renew or fix — don't just extend silently.

## SBOM workflow

`sbom/prod-sbom.json` is a CycloneDX 1.6 software bill of materials covering every production dependency. It is a **tracked artefact**, not a build output.

- Regenerated via `make sbom` after any change to `prod.txt`.
- Committed in the same commit as the dep change.
- Diffs cleanly across commits (sorted JSON) — a future incident-response reviewer can `git diff` to see exactly what transitive changed across a release.
- Currently 71 components (matches the top-level pin count in `prod.txt`).
- `make sbom-diff` regenerates a fresh SBOM and diffs the `(name, version, purl)` component set against the committed file. Use it before merging a PR that didn't touch `requirements/*.in` to flag silent transitive additions — e.g. a hash refresh that pulled in a new wheel via an existing transitive.

## Policy boundaries

- **Never** bump dep versions inside a feature PR. Dep refreshes go in dedicated `chore(deps): …` commits so they're reviewable and revertible.
- **Never** add a dep without an upper bound.
- **Never** commit `requirements/*.txt` edits without the corresponding `.in` change + regenerated hashes.
- **Never** skip `--allow-unsafe` when regenerating `dev.txt` — the layer won't install under `--require-hashes` without it.
- The SBOM is committed alongside any dep change. A PR that edits `prod.txt` without touching `sbom/prod-sbom.json` is incomplete.
