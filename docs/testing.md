# Testing

The boilerplate ships a three-layer pytest setup: **unit**, **integration**,
**e2e**. Each layer has a clear contract; the harness auto-marks tests by
directory so you rarely write `@pytest.mark.<layer>` by hand.

> **Config:** `pytest.ini` (markers + discovery) · `.coveragerc` (coverage
> rules) · **Top-level fixtures:** `tests/conftest.py` · **Factories:**
> `tests/factories.py` · **Per-layer fixtures:**
> `tests/{unit,integration,e2e}/conftest.py`

## Layer contract

| Layer | Touches | Speed | Where |
|---|---|---|---|
| **unit** | Pure Python; every boundary mocked. No DB, no cache, no network. | < 10 ms / test | `tests/unit/` + `apps/*/tests/` (default) |
| **integration** | DB + cache + broker (eager). Single process. No HTTP client. | 10–500 ms / test | `tests/integration/` |
| **e2e** | Full DRF `APIClient` round-trip: URL → middleware → view → service → ORM → response envelope. | 50 ms–2 s / test | `tests/e2e/` |
| **slow** | Anything > 1 s. Excluded from default runs. | — | mark with `@pytest.mark.slow` |
| **external** | Hits a real third-party service. Opt-in only. | — | mark with `@pytest.mark.external` |

The auto-marking lives in `tests/conftest.py::pytest_collection_modifyitems`:
files under `tests/unit/`, `tests/integration/`, `tests/e2e/`, and
`apps/*/tests/` (defaults to `unit`) are tagged automatically. Overriding
the default is one decorator on the test.

## Running the suites

```bash
# Full default suite (unit + integration + e2e, skipping slow + external)
make test

# Single layer
make test-unit
make test-integration
make test-e2e

# Coverage — terminal report + XML for CI + HTML for local browsing
make test-cov            # terminal + XML
make test-cov-html       # also writes htmlcov/index.html
make test-cov-open       # macOS/Linux: open the HTML report

# Slow / external suites (opt-in)
make test-slow
make test-external

# Pass-through to pytest
make test ARGS="-k api_key -x"
```

Direct pytest also works:

```bash
DJANGO_ENV=test pytest -m unit                  # one layer
DJANGO_ENV=test pytest -m "integration or e2e"  # multi-layer
DJANGO_ENV=test pytest tests/e2e/ -x            # by path, stop on first fail
DJANGO_ENV=test pytest --cov --cov-report=html  # ad-hoc coverage run
```

## Shared fixtures

From `tests/conftest.py`:

| Fixture | What it gives you |
|---|---|
| `api_client` | Unauthenticated `rest_framework.test.APIClient` |
| `user` | A single fresh active user (uses `UserFactory`) |
| `user_factory` | Callable: `user_factory(email="…", is_staff=True, …)` |
| `authed_api_client` | `APIClient` already authenticated as `user` (attribute `.user` set) |
| `superuser_api_client` | `APIClient` authenticated as a Django superuser |
| `settings_override` | Alias for pytest-django's `settings` fixture |
| `_clear_caches` (autouse) | Clears all Django caches between tests |

Integration and e2e conftests autouse the `db` fixture so you don't have to
opt in per-test. Unit tests intentionally do not — if a unit test needs the
DB, move it to integration.

## Factories

`tests/factories.py` ships `UserFactory`. Conventions:

- Keep factories thin — only the fields needed for a valid row.
- Per-test customisation goes in the test (`UserFactory(email="x@…")`), not
  in the factory.
- App-specific factories that depend on app models go in
  `apps/<name>/tests/factories.py` and subclass `UserFactory` where useful.

```python
from tests.factories import UserFactory

def test_x():
    u = UserFactory(email="alice@example.com", is_staff=True)
    assert u._raw_password == "password123"  # default; override with password=
```

## Coverage

`.coveragerc` is the single source of truth. Key settings:

- `source = apps` — only project code is measured (no third-party).
- `branch = True` — branch coverage on by default.
- `omit` — migrations, tests, `__pycache__`, `apps.py`, `admin.py`, urls,
  and the config module are excluded.
- `fail_under = 70` — the suite fails if total coverage drops below 70%.
  Bump this number as the codebase matures; resist lowering it.
- `exclude_lines` — `pragma: no cover`, `if TYPE_CHECKING:`, ellipses, and
  `raise NotImplementedError` lines are not counted against you.

Outputs:
- Terminal: `make test-cov` (shows missing lines).
- HTML: `htmlcov/index.html` (browsable, gitignored).
- XML: `coverage.xml` (CI ingestion — Codecov, Coveralls, etc.).

CI should run `make test-cov` and either upload `coverage.xml` or fail on
the configured `fail_under` threshold.

## Writing tests

### Unit

```python
# tests/unit/test_normalise.py

def test_normalise_email_lowercases_and_strips():
    from accounts.utils import normalise_email
    assert normalise_email(" Alice@Example.COM ") == "alice@example.com"
```

### Integration

```python
# tests/integration/test_user_service.py

def test_create_user_sets_audit_fields(user_factory):
    from accounts.services import UserService
    actor = user_factory()
    created = UserService().create(
        {"email": "new@example.com"},
        user=actor,
    )
    assert created.created_by_id == actor.pk
```

### E2E

```python
# tests/e2e/test_login_flow.py

def test_login_returns_jwt(api_client, user_factory):
    user = user_factory(email="login@example.com", password="s3cret!")
    resp = api_client.post(
        "/api/accounts/login/",
        {"email": user.email, "password": "s3cret!"},
        format="json",
    )
    assert resp.status_code == 200
    assert "access" in resp.json()["data"]
```

## CI integration (sketch)

```yaml
# .github/workflows/ci.yml (excerpt)
- name: Run tests with coverage
  run: make test-cov
  env:
    DJANGO_ENV: test
    POSTGRES_HOST: localhost
- name: Upload coverage
  uses: codecov/codecov-action@v4
  with:
    files: ./coverage.xml
```

## Gotchas

- **`tests/unit/` cannot use the `db` fixture.** Move the test to integration.
- **`APIClient` does not retry the request when middleware raises.** Use
  `assert resp.status_code == 5xx` rather than expecting an exception.
- **Celery runs eagerly in tests** (`CELERY_TASK_ALWAYS_EAGER = True`).
  Tasks dispatched via `transaction.on_commit` only fire once the outer
  transaction commits — use `pytest-django`'s `django_db(transaction=True)`
  marker if you need true commit semantics.
- **Throttling and SSRF blocks are disabled in test settings** — see
  `config/settings/test.py`. If you're testing throttle headers / SSRF
  enforcement, re-enable them with `settings_override`.
- **Cache state leaks between tests** unless the autouse `_clear_caches`
  fixture runs. Don't disable it.

## Related docs

- [development.md](development.md) — running the app locally.
- [observability.md](observability.md) — what to assert when testing
  metric / log emission.
- [audit-trail.md](audit-trail.md) — what audit fields a test should
  assert on after mutating operations.
