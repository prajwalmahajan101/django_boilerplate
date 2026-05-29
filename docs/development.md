# Development Guide

## Prerequisites

- Docker and Docker Compose
- Git

Optional (for running tools outside Docker):
- Python 3.12+
- pip-tools (`pip install pip-tools`)

## Initial Setup

### 1. Clone and Configure

```bash
git clone <repository-url>
cd co-lending-gateway
cp environment/.env.example environment/.env.local
```

Edit `environment/.env.local`:
```bash
DJANGO_ENV=local
SECRET_KEY=your-random-secret-key-here
# All other values have sensible defaults for local development
```

### 2. Start Services

```bash
docker compose up --build
```

This starts all services:
| Service | Description | Port |
|---|---|---|
| web | Django dev server (hot-reload) | 8000 |
| nginx | Reverse proxy + rate limiting | 80 |
| db | PostgreSQL 16 | 5432 |
| valkey | Valkey 8 (cache + rate limiting) | 6379 |
| rabbitmq | RabbitMQ 3.13 (task broker) | 5672, 15672 (mgmt) |
| celery_worker | Celery worker (threads, concurrency=4) | -- |
| celery_beat | Celery beat scheduler | -- |
| flower | Celery monitoring UI | 5555 |

### 3. Initialize Database

```bash
docker exec co-lending-gateway-web-1 python manage.py migrate
docker exec co-lending-gateway-web-1 python manage.py createsuperuser
```

### 4. Verify

- API: http://localhost:8000/api/health/
- Swagger: http://localhost:8000/api/docs/
- Admin: http://localhost:8000/admin/
- RabbitMQ: http://localhost:15672/ (guest/guest)
- Flower: http://localhost:5555/ (admin/changeme)

## Project Structure

All domain apps live under `apps/`. Both `manage.py` and `config/settings/__init__.py` add `apps/` to `sys.path`, so imports use:
```python
from accounts.models import User      # not apps.accounts.models
from core.base.service import BaseService
```

## Code Patterns

### Adding a New Model

1. Create model inheriting `BaseModel` or `NamedBaseModel`:
   ```python
   # apps/myapp/models.py
   from core.base.model import NamedBaseModel

   class MyModel(NamedBaseModel):
       custom_field = models.CharField(max_length=255)

       class Meta:
           db_table = "myapp_mymodel"
   ```

2. Create migrations:
   ```bash
   docker exec co-lending-gateway-web-1 python manage.py makemigrations myapp
   docker exec co-lending-gateway-web-1 python manage.py migrate
   ```

### Adding a New Service

```python
# apps/myapp/services.py
from core.base.service import BaseService
from myapp.models import MyModel

class MyModelService(BaseService[MyModel]):
    model = MyModel
    allowed_filter_fields = frozenset({"name", "code", "is_active"})

    def pre_create(self, data: dict, user) -> dict:
        # Custom validation or transformation before create
        return data

    def post_create(self, instance: MyModel, user) -> None:
        # Side effects after create (logging, cache invalidation, etc.)
        pass
```

### Adding a New View

```python
# apps/myapp/views.py
from rest_framework.views import APIView
from core.enums import Resource, Action
from core.responses import SuccessResponse, PaginatedResponse
from core.utils.pagination import StandardPageNumberPagination

class MyModelListCreateView(APIView):
    resource = Resource.MY_RESOURCE  # Add to enums.py first

    def initial(self, request, *args, **kwargs):
        self.action = Action.READ if request.method == "GET" else Action.CREATE
        super().initial(request, *args, **kwargs)

    def get(self, request):
        service = MyModelService()
        paginator = StandardPageNumberPagination()
        queryset = service.list_active()
        page = paginator.paginate_queryset(queryset, request)
        serializer = MyModelSerializer(page, many=True)
        return PaginatedResponse(
            data=serializer.data,
            page=paginator.page,
        )

    def post(self, request):
        serializer = MyModelCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = MyModelService()
        instance = service.create(serializer.validated_data, request.user)
        return SuccessResponse(
            data=MyModelSerializer(instance).data,
            status_code=201,
        )
```

### Adding a New RBAC Resource

1. Add to `core/enums.py`:
   ```python
   class Resource(models.TextChoices):
       # ... existing
       MY_RESOURCE = "MY_RESOURCE", "My Resource"
   ```

2. Create Permission records (via admin or migration):
   ```python
   Permission.objects.create(resource="MY_RESOURCE", action="CREATE")
   Permission.objects.create(resource="MY_RESOURCE", action="READ")
   # etc.
   ```

3. Assign to roles via admin panel.

### Making External Service Calls

```python
from core.resilience.decorators import resilient
from core.utils.http_client import make_http_request

@resilient("my_external_service")
def call_external_api(data):
    response = make_http_request(
        method="POST",
        url="https://api.external.com/endpoint",
        json_body=data,
        timeout=30,
    )
    return response.body
```

Register custom resilience config in `AppConfig.ready()` if defaults aren't suitable:
```python
from core.resilience.registry import registry

class MyAppConfig(AppConfig):
    def ready(self):
        registry.register_service("my_external_service", {
            "circuit_breaker": {"fail_max": 3, "reset_timeout": 60},
            "retry": {"max_attempts": 5},
        })
```

### Serializer Pattern

Always separate read and write serializers:

```python
# Read serializer (exclude sensitive fields)
class MyModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = MyModel
        exclude = ["sensitive_field"]

# Create serializer
class MyModelCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MyModel
        fields = ["name", "code", "custom_field"]

# Update serializer (all fields optional)
class MyModelUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MyModel
        fields = ["name", "custom_field"]
        extra_kwargs = {f: {"required": False} for f in fields}
```

## Dependency Management

Dependencies use pip-tools (`.in` files define requirements, `.txt` files are locked):

```bash
# Add a new dependency
echo "new-package>=1.0" >> requirements/base.in

# Recompile lock file
pip-compile requirements/base.in

# Sync local environment
pip-sync requirements/dev.txt

# Audit for CVEs
pip-audit -r requirements/base.txt
```

| File | Purpose |
|---|---|
| `requirements/base.in` | Core runtime dependencies |
| `requirements/dev.in` | Development extras (debug toolbar, ipython, pip-tools) |
| `requirements/test.in` | Test extras (pytest, factory-boy) |
| `requirements/prod.in` | Production extras (gunicorn) |

## Testing

```bash
# Run all tests
docker exec co-lending-gateway-web-1 pytest

# With coverage
docker exec co-lending-gateway-web-1 pytest --cov

# Run specific test file
docker exec co-lending-gateway-web-1 pytest apps/accounts/tests/test_views.py

# Run specific test
docker exec co-lending-gateway-web-1 pytest -k "test_login"
```

Test settings (`config/settings/test.py`):
- Uses PostgreSQL (not SQLite) to catch JSONB/constraint issues
- Fast password hasher (MD5)
- In-memory caches (no Valkey needed)
- Celery eager mode (tasks run synchronously)
- Throttling disabled
- AllowAny permissions (simplifies API test setup)

### Writing Tests

```python
# apps/myapp/tests/test_views.py
import pytest
from rest_framework.test import APIClient

@pytest.mark.django_db
class TestMyModelListView:
    def setup_method(self):
        self.client = APIClient()

    def test_list_returns_active_only(self, user):
        self.client.force_authenticate(user=user)
        response = self.client.get("/api/myapp/")
        assert response.status_code == 200
        assert response.data["success"] is True
```

### Testing patterns

Patterns you'll hit often in this codebase, with their canonical solutions.

**Mocking Synoriq reads.** `LeadsDataService` is the boundary — patch it at the highest level you can. `fetch_all_details` returning `None` is a valid production state (Synoriq data lags), so make sure at least one test exercises that branch:

```python
from unittest.mock import patch
from types import SimpleNamespace

@patch("queries.services.assignment_engine.LeadsDataService")
def test_engine_falls_open_on_missing_lead(mock_service):
    mock_service.return_value.fetch_all_details.return_value = None
    # ... engine still returns a user (or None if no default rule)
```

For broader tests that exercise `LeadsDataService` itself, patch at the strategy layer (`SqlLeadsStrategy`) so the service's own logic runs.

**Celery tasks in tests.** `config/settings/test.py` sets `CELERY_TASK_ALWAYS_EAGER = True` — tasks run synchronously in the test process. No broker, no worker. If you need to assert the task *was scheduled* without executing, temporarily set `CELERY_TASK_ALWAYS_EAGER = False` and inspect `celery.current_app.tasks`.

**`transaction.on_commit`-dispatched tasks.** Django's `TestCase` wraps each test in a transaction that rolls back at teardown — `on_commit` callbacks *never fire* by default. For tests that need the callback to execute, wrap the call site in `captureOnCommitCallbacks(execute=True)`:

```python
def test_remark_processing_sends_email(self):
    with self.captureOnCommitCallbacks(execute=True):
        service.check_and_process(sub_query)
    mock_send_email.assert_called_once()
```

See `apps/queries/tests/test_remark_processing_service.py` for the canonical example.

**Testing `BaseService` hooks.** The hook contract is `pre_create(data, user)` / `post_create(instance, user)` / `pre_update` / `post_update` / `pre_delete` / `post_delete(instance, user=None)`. Override the hook, call the service method, then assert on the instance. Don't call hooks directly — always go through `service.create/update/delete` so the `@transaction.atomic` wrapping runs. Tests covering cascade `post_delete(instance, user)` MUST pass a user through so subclass overrides stamp `updated_by` correctly.

**Concurrency-sensitive code.** Use `TransactionTestCase` (not the default `TestCase`) so each thread sees the others' committed rows. Example: `apps/queries/tests/test_assignment_engine.py::RoundRobinConcurrencyTest` spins 10 threads against a 3-user pool and asserts a deterministic 4/3/3 distribution.

**AllowAny in tests.** The default test permission is `AllowAny` (set in `config/settings/test.py`). To exercise real RBAC in a test, explicitly set `permission_classes = [IsAuthenticated, HasResourcePermission]` on a test-scoped view subclass, or use `override_settings(REST_FRAMEWORK={...})`.

### Debugging

**Enter the web container shell:**

```bash
docker compose exec web bash
# or for one-shot Python:
docker compose exec web python manage.py shell_plus
```

`shell_plus` auto-imports all models and common `django.db.models` helpers — faster than plain `shell` for interactive ORM work.

**Inspect the Django DB interactively:**

```bash
docker compose exec web python manage.py dbshell   # psql as the app user
docker compose exec db psql -U postgres co_lending_gateway
```

**Inspect the Synoriq DB (read-only path):**

```python
# Inside shell_plus
from core.utils.db import build_url, get_engine, execute_query
from django.conf import settings
engine = get_engine(build_url(**settings.SYNORIQ_DB))
result = execute_query(engine, "SELECT COUNT(*) FROM applications", {})
result.scalar
```

**Check Celery queue state:**

```bash
# Flower UI
open http://localhost:5555

# Or from the container
docker compose exec celery_worker celery -A config.celery inspect active
docker compose exec celery_worker celery -A config.celery inspect reserved
```

**Inspect Valkey (cache + rate-limit aliases):**

```bash
docker compose exec valkey redis-cli
# Useful commands:
> SELECT 0                  # default cache
> KEYS "*"
> SELECT 1                  # rate_limit cache
> KEYS "throttle:*"
```

**Drop into pdb from a failing test:**

```bash
docker compose exec web pytest -x --pdb apps/queries/tests/test_assignment_engine.py
```

### Observability

Logs are structured JSON (next section). On top of that, the codebase ships a small observability primitive.

**`log_duration` context manager.** `apps/core/utils/logging.py::log_duration` times a block and emits one structured log line on exit — INFO with `duration_ms` + `ok=True` on success, ERROR with `ok=False` on exception (and re-raises, preserving traceback). Any caller-supplied extras are forwarded to the log record.

```python
from core.utils.logging import log_duration

with log_duration(logger, "assignment_rr_pick", rule_id=rule.pk, pool_size=len(users)):
    with connection.cursor() as cursor:
        cursor.execute(...)
```

Canonical usage lives in `apps/queries/services/assignment_engine.py::_pick_user_round_robin` — the block wraps the raw `UPDATE ... RETURNING` so production can plot round-robin latency per-rule without touching the caller.

When to use it:
- Any hot-path DB call whose p95 could matter later.
- Any external-system call that isn't already wrapped in `@resilient` (the decorator emits timing internally).
- Anything you'd otherwise Measure manually with `time.perf_counter()` bookends.

When not to use it:
- Inside tight loops — one log line per iteration is noisy.
- When the metric belongs in a metrics backend (Prometheus, CloudWatch embedded metrics) rather than logs.

**`RequestContextFilter`.** `apps/core/utils/logging.py::RequestContextFilter` pulls `request_id` from a `contextvars.ContextVar` and attaches it to every log record the filter sees. The ContextVar is set by `RequestIDMiddleware` on ingress and cleared on response. Net result: every log line emitted during a request carries the same `request_id`, which threads through Celery task dispatches too (set by the dispatcher, read by the worker).

Attach the filter to any logger or handler via `logging.config.dictConfig`. The default `LOGGING` setting already does this for the root logger.

## Database Operations

### Primary Database (Django ORM)

```bash
# Create migrations
docker exec co-lending-gateway-web-1 python manage.py makemigrations <app_name>

# Apply migrations
docker exec co-lending-gateway-web-1 python manage.py migrate

# Show migration status
docker exec co-lending-gateway-web-1 python manage.py showmigrations
```

### External Database (SQLAlchemy)

The Synoriq database is accessed via `core/utils/db.py`:
```python
from core.utils.db import build_url, execute_query, get_engine

engine = get_engine(build_url(host="synoriq-db.internal", name="synoriq"))
result = execute_query(
    engine,
    "SELECT * FROM applications WHERE app_no = :app_no",
    {"app_no": "APP-001"},
)
# result.objects -> list of SimpleNamespace
# result.first   -> first row as SimpleNamespace (or None)
# result.scalar  -> first cell value (or None)
```

`build_url()` fills blanks from `DATABASES["default"]` so only the host/name that differ need to be passed. `get_engine()` caches one engine per URL for the process; it also applies a 5s connect timeout and a 30s server-side statement timeout so Synoriq queries can't hang the worker.

Never use Django ORM for the Synoriq database. Never use SQLAlchemy for the primary database.

## Logging

All logs are structured JSON via python-json-logger:

```python
import logging
logger = logging.getLogger(__name__)

logger.info("Processing lead", extra={
    "app_number": "APP-001",
    "partner_id": 5,
})
```

Output:
```json
{
  "message": "Processing lead",
  "levelname": "INFO",
  "name": "partners.services.push",
  "request_id": "550e8400-...",
  "app_number": "APP-001",
  "partner_id": 5,
  "timestamp": "2025-03-01T14:30:00.000Z"
}
```

Sensitive fields (password, secret, token, key, auth, credential, bearer, jwt) are automatically masked in logs.

## Git Workflow

| Branch | Purpose |
|---|---|
| `main` | Production-ready code |
| `dev` | Development/staging |
| `feature/<name>` | Feature branches (branch from `dev`) |

Commit messages use conventional format:
```
feat: add partner push-lead endpoint
fix: correct bearer token cache invalidation
refactor: extract auth handler strategy pattern
docs: update API reference with push-lead examples
```
