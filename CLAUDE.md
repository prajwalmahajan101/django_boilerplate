# Django Boilerplate

> A Django 6 + DRF starter with vetted core infrastructure. See
> [README.md](README.md) for quickstart, [docs/](docs/) for the full
> infrastructure reference.

## Key conventions

- **Views → Services → ORM.** Views never touch the ORM; services
  never construct HTTP responses.
- **`BaseService[T]`** — all services inherit this; use
  `pre_*` / `post_*` hooks; writes run under `@transaction.atomic`
  + `select_for_update()`.
- **Response envelopes.** Always `SuccessResponse` / `ErrorResponse`
  / `PaginatedResponse` from `core/responses/`.
- **Typed exceptions** from `core/exceptions/`; never bare
  `raise Exception`.
- **RBAC.** Views set `resource` + `action` class attrs; checked by
  `HasResourcePermission` from `core/permissions.py`.
- **Structured logging.** `logger = logging.getLogger(__name__)`;
  JSON format; never log raw credentials. Use
  `core.utils.logging.log_duration` to time hot-path blocks.
- **Sensitive data.** `EncryptedCharField` at rest;
  `log_sanitization` for log output.
- **External calls** wrap with `@resilient("service_name")` from
  `core/resilience/`. Register the service in
  `core.apps.CoreConfig._register_resilience_services`.
- **Env vars** — document new ones in `environment/.env.example`;
  use `_env_int()` / `_env_bool()` helpers.
- **Thread-safety** — gthread Gunicorn shares worker processes
  across threads. Module-level mutable state must match a documented
  pattern. See [docs/thread-safety.md](docs/thread-safety.md).
- **Dependencies** — layered pip-tools with `--generate-hashes`;
  `dev.txt` needs `--allow-unsafe`. See
  [docs/dependency-management.md](docs/dependency-management.md).

## Naming conventions

- **Verb hierarchy for data access.** `execute_*` for raw SQL
  primitives (needs an engine). `get_*` for single-entity ORM
  fetches. `fetch_*` for external-system reads (third-party APIs,
  AWS). Don't mix verbs at the same tier.
- **Leading underscore means internal-only** to the defining class
  or module. If a method is called from a sibling class or another
  module, drop the underscore.
- **Describe the observable effect, not the tactic.**
  If a name could describe ten different methods, it's too generic.
- **`*Service` / `*Handler` / `*Engine` suffix** only when the bare
  noun would be ambiguous with a model or domain term.

## Commands

```bash
DJANGO_ENV=local python manage.py runserver
DJANGO_ENV=test  python manage.py test
make audit deps-check sbom          # see Makefile for the full set
pip-compile requirements/base.in    # refresh pinned deps
pre-commit run --all-files          # lint + format + sync check
```

## Settings

`DJANGO_ENV` selects the module (`local` / `dev` / `uat` / `prod` /
`test`). Full catalog + AWS Secrets Manager overlay in
[docs/configuration.md](docs/configuration.md).

## Default RBAC resources

`ACCOUNT`, `ROLE`, `API_KEY`. Actions: `CREATE`, `READ`, `UPDATE`,
`DELETE`. Extend `core/enums.py` per-domain; mirror new resources in
`accounts/backends.py::RBACBackend.MODEL_RESOURCE_MAP`.

## Git workflow

- Conventional commits: `feat:`, `fix:`, `chore:`, `refactor:`,
  `perf:`, `test:`, `docs:`, `style:`.
- One logical change per commit. Dep refreshes go in `chore(deps):`
  commits.
