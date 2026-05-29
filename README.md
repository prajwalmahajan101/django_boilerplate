# Django Boilerplate

A production-grade Django 6 + DRF starter. Ships with:

- **`apps/core/`** — base classes (`BaseModel`, `BaseService[T]`),
  typed exception hierarchy + DRF handler, structured response
  envelopes (`SuccessResponse` / `ErrorResponse` / `PaginatedResponse`),
  request-id middleware, request/response logging, rate-limit headers,
  resilience primitives (retry + circuit breaker + Valkey-backed
  throttles), AWS utilities (boto3 thread-local caches, S3, SES),
  HTTP client with SSRF guard, log sanitization, cursor + offset
  pagination, fire-and-forget Celery dispatch, Prometheus-ready
  metrics shim.
- **`apps/accounts/`** — `User` (email login), `Role` / `Permission`
  RBAC, `APIKey` (prefix-indexed, encrypted at rest), JWT via
  `dj-rest-auth`, Google OAuth via `django-allauth`, `RBACBackend`
  mapping Django admin perms to `(Resource, Action)` tuples,
  `HasResourcePermission` DRF guard with per-request cache.
- **`config/`** — `DJANGO_ENV`-driven settings (`local` / `dev` /
  `uat` / `prod` / `test`) with an AWS Secrets Manager overlay.
- **`requirements/`** — layered `pip-tools` setup
  (`base.in` → `base.txt`, plus `dev`, `prod`, `test`) with hashed
  resolved files.
- **Pre-commit** — `ruff` (lint + format), `pydocstyle`, `darglint`,
  auto pip-compile sync, and a custom `check_dead_utils` script
  catching unused public symbols under `apps/core/`.
- **Docker** — multi-stage Dockerfile (non-root, gunicorn gthread),
  docker-compose with Postgres 16, Valkey 8, and nginx.
- **`docs/`** — architecture, thread-safety contract, resilience
  decorators, exception hierarchy, observability, configuration,
  dependency management, deployment, authentication.

## Quickstart

```bash
cp environment/.env.example environment/.env.local
# fill in SECRET_KEY, POSTGRES_*, VALKEY_CACHE_URL, CELERY_BROKER_URL,
# JWT_SIGNING_KEY, FIELD_ENCRYPTION_KEY, optional GOOGLE_OAUTH2_*

docker compose up -d db valkey
pip install -r requirements/dev.txt
DJANGO_ENV=local python manage.py migrate
DJANGO_ENV=local python manage.py createsuperuser
DJANGO_ENV=local python manage.py runserver 0.0.0.0:8000
```

Open `/api/docs/` for Swagger UI and `/admin/` for the Unfold admin.

## Documentation

- **[docs/architecture.md](docs/architecture.md)** — system overview,
  layering, encryption, async stack.
- **[docs/adding-a-new-app.md](docs/adding-a-new-app.md)** —
  step-by-step contract for onboarding a new domain app.
- **[docs/data-model.md](docs/data-model.md)** — `BaseModel`,
  `BaseService[T]`, validation contract, page-size cap.
- **[CHANGELOG.md](CHANGELOG.md)** — release notes.

Full doc index: **[docs/INDEX.md](docs/INDEX.md)** (resilience,
thread-safety, exceptions, observability, configuration, dependency
management, deployment, authentication, audit trail, scalability,
Celery topology, and the recommended reading order for new
contributors).

## Renaming for your project

1. Edit `SPECTACULAR_SETTINGS["TITLE"]` and `UNFOLD["SITE_HEADER"]` in
   `config/settings/base.py`.
2. Extend `apps/core/enums.py` (`Resource` and `Action`) with the
   nouns your domain owns; each new app registers its own
   `Resource ↔ Model` mappings via
   `core.rbac_registry.register_resource()` from its
   `AppConfig.ready()` — no edit to `apps/accounts/backends.py` is
   required. See
   [docs/adding-a-new-app.md](docs/adding-a-new-app.md) §3.
3. Add new apps under `apps/<name>/`; register them in
   `INSTALLED_APPS` and wire their URLs in `config/urls.py`.
4. Re-run `pip-compile` (or let pre-commit do it) after editing
   `requirements/*.in`.

## Verification (smoke checks)

```bash
DJANGO_ENV=test python -c "import django; django.setup()"
DJANGO_ENV=test python manage.py makemigrations --check --dry-run
pre-commit install && pre-commit run --all-files
python scripts/check_dead_utils.py
```

## Conventions

See `CLAUDE.md` for the **Views → Services → ORM** layering, response
envelope contract, naming verb hierarchy (`execute_*` / `get_*` /
`fetch_*`), thread-safety contract, and git workflow.
