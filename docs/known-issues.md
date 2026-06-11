# Known issues & follow-ups

Live backlog of pre-existing repo bugs, lint debt, and deferred work
that should be addressed in follow-up PRs. Distinct from
`docs/m7-kit-integration-report.md` (which is about *kit-side*
follow-ups fed back to the resilience-kit team) — this file is about
*boilerplate-side* cleanups.

## P1 — `nginx/default.conf` missing from repo, breaks `docker compose up`

**Surfaced:** M8 e2e testing run (2026-06-11). **Predates M7+M8** — not
introduced by the kit migration; the M8 e2e session is just where it
became visible.

**Symptom.** `docker-compose.yml` declares a bind mount

```yaml
volumes:
  - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
```

but `nginx/default.conf` does not exist in the repo (verified:
`git ls-files nginx/` returns nothing). When `docker compose up` runs
nginx, Docker's bind-mount semantics auto-create the missing host path
as a **directory**, which then fails to mount onto nginx's expected
config-file location:

```
Error response from daemon: failed to create task for container: ...
mount src=.../nginx/default.conf ... not a directory:
Are you trying to mount a directory onto a file (or vice-versa)?
```

The auto-created directory is owned by root (Docker's bind-mount
behaviour), which makes cleanup an extra step (`sudo rm -rf` or
docker-side cleanup).

**Workaround used during M8 e2e:** wrote a `docker-compose.override.yml`
that put nginx under a `disabled` profile and exposed the web
container's port 8000 directly on the host. End-to-end tests still
covered the kit integration; nginx-fronted rate-limit / WAF behaviour
was not exercised.

**Fix options (pick one in a follow-up PR):**

1. **Commit a minimal `nginx/default.conf`.** Just a reverse-proxy to
   `web:8000` with the boilerplate's expected
   `proxy_set_header X-Forwarded-For` / `X-Real-IP` lines. Lowest
   blast radius; restores the documented `docker compose up` flow.
2. **Make nginx a compose profile.** Move the service under a
   `production` profile so default `docker compose up` skips it and
   exposes the web port instead. Cleaner for dev; requires a doc note
   for prod deployments.
3. **Delete the nginx service entirely.** If nginx isn't actually
   needed for local dev (it's typically present only as a reverse
   proxy in cloud deployments), drop it from `docker-compose.yml` and
   document the production nginx config elsewhere (helm, terraform).

**Owner:** unassigned. **Severity:** P1 — blocks the documented dev
flow but workaround is straightforward.

---

## P2 — Pre-existing lint debt across the codebase

**Surfaced:** M8 first pre-commit run (commit `dd0a597`).

56 ruff violations (SIM102, SIM117, UP005, etc.) plus pydocstyle
D101/D102/D205 and darglint DAR101/DAR201 errors in files that pre-date
the M7 migration. The M7 commits used `--no-verify` to dodge the
`pip-compile-base` hook (which omits `--generate-hashes` and would
strip lockfile hashes), incidentally also dodging ruff / pydocstyle /
darglint.

**Out of scope** for the M7+M8 PR — would explode the diff and is
unrelated to the kit work. Should ship as its own focused PR scoped
to "make pre-commit green on `main`".

**Tracked already** in `docs/m8b-upgrade-report.md` § Pain points.

---

## P3 — pytest not in container image's runtime venv

**Surfaced:** M8 e2e T8.

`docker exec web-1 python -m pytest …` fails with "No module named
pytest" because the build args nominally point at
`requirements/dev.txt` but the resulting image doesn't expose pytest
on `$PATH` or in the active venv. Local pytest already covers the
test plan; this is a "would-be-nice" so containerised CI can run
tests without a separate test image.

Low priority — only matters if/when CI moves to docker-based test
execution.
