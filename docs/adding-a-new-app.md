# Adding a new domain app

> Companion to [architecture.md](architecture.md) (layering),
> [exceptions.md](exceptions.md) (exception registration),
> [resilience.md](resilience.md) (`@resilient` registration),
> and [audit-trail.md](audit-trail.md) (soft-delete cascade contract).

This is the single source of truth for what must be wired when you drop a
new app next to `apps/accounts/`. Every step exists because something in
`core` or in cross-cutting machinery (RBAC, admin, OpenAPI, breakers)
will silently misbehave if you skip it.

## 1. Scaffolding

```bash
python manage.py startapp my_app apps/my_app
```

The `apps/` prefix is on `sys.path` (see the duplicated guard in
`config/celery.py` + `config/settings/__init__.py`), so internal imports
read as `from my_app.models import Foo`, not `from apps.my_app.models …`.

Add the app to `INSTALLED_APPS` in `config/settings/base.py`. Use the
short label (`"my_app"`), not the dotted path.

## 2. Models

Inherit `BaseModel` (audit fields, soft-delete, validation contract) or
`NamedBaseModel` (adds `name` + unique `code`). Both live in
`apps/core/base/model.py`.

When you override `Meta` on a concrete model, inherit from
`BaseModel.Meta` so the abstract's `CheckConstraint`
(`updated_at >= created_at`) propagates:

```python
class MyModel(BaseModel):
    ...
    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        indexes = [...]   # your additions
```

If you forget this inheritance, the audit invariant is enforced at the
service layer only — admin / shell / raw-SQL can smuggle in violating
rows.

## 3. RBAC

Two coordinated edits — and one call from your `AppConfig.ready()`:

1. Extend `Resource` in `core/enums.py` with one entry per top-level
   resource your app owns. Actions (`CREATE`, `READ`, `UPDATE`,
   `DELETE`) almost never need extending.
2. Register each of your models against the right resource from
   `apps/my_app/apps.py::ready()`:

   ```python
   from core.enums import Resource
   from core.rbac_registry import register_resource

   register_resource("my_app.foo", Resource.FOO)
   register_resource("my_app.bar", Resource.BAR)
   ```

   You do **not** edit `RBACBackend.MODEL_RESOURCE_MAP` — the backend
   reads from the registry, populated by every app's `ready()`. Models
   you omit fall back to denied; that is the safe default, not a bug.
3. Set `resource = Resource.X` and `action = Action.Y` (or override
   `initial()`) on every view that uses `HasResourcePermission`.

## 4. Services & repositories

- One service per top-level resource, inheriting `BaseService[Model]`
  from `core/base/service.py`. Use `pre_*` / `post_*` hooks; never call
  `.save()` directly from a view.
- Services are instantiated per call (`MyService().do_thing(...)`), not
  as module-level singletons.
- Repositories own the lock contract — if a write needs
  `select_for_update`, put it in the repository, not in the service.

## 5. Exceptions

Add domain exceptions in `apps/my_app/exceptions.py`, subclassing the
typed base from `core/exceptions/`. Register the status-code mapping in
`apps/my_app/apps.py::ready()`:

```python
from django.apps import AppConfig


class MyAppConfig(AppConfig):
    name = "my_app"

    def ready(self):
        from core.exceptions.registry import register_exception_mapping
        from my_app import exceptions as exc

        register_exception_mapping(exc.MyDomainError, 422)
```

`error_code` is auto-derived from the class name — do not pass it.

## 6. Resilience

Wrap every external call with `@resilient("my_service_name")`, then
register the service config in `apps/core/apps.py::CoreConfig.ready()`
(or, if your app owns the resilience config, in your own
`AppConfig.ready()`). The registration sets breaker thresholds, retry
policy, and timeout. Unregistered service names fall back to defaults
and emit a WARNING the first time they trip.

## 7. Tasks (Celery)

If your app declares periodic / async tasks, route them explicitly via
`CELERY_TASK_ROUTES` in `config/settings/base.py` so they land on the
right priority queue. Leaving the route unset sends every task to
`default` and the declared `high_priority` / `low_priority` queues stay
empty.

## 8. Soft-delete cascade

`BaseService.delete(pk, soft=True, user=...)` walks related objects via
`_cascade_soft_delete_bfs` (bounded BFS with depth-cap). The walk picks
up any model with a `is_active` field and an FK back to the deleted
instance. If your app has custom cascade semantics (e.g. a child that
should *not* deactivate when the parent does), override `post_delete`
on the relevant service and propagate `user=` so audit rows get
`updated_by` stamped.

## 9. OpenAPI schemas

Domain-specific schemas live in `apps/my_app/api_schemas/<resource>.py`.
Reuse shared envelope helpers from `core.api_schemas` —
`envelope_schema`, `paginated_envelope_schema`, `throttle_response`,
`forbidden_response`, etc. Never duplicate them.

## 10. Tests

- Unit + integration tests under `apps/my_app/tests/` follow the
  existing pattern (TestCase + `assertNumQueries` budgets for hot paths).
- Cross-app integration tests under `tests/integration/`.
- Slow / external-dependency tests are opt-in via the markers wired in
  `tests/conftest.py`.

## Checklist

- [ ] `apps/my_app/` scaffolded and listed in `INSTALLED_APPS`
- [ ] Models extend `BaseModel`/`NamedBaseModel`; `Meta` inherits
- [ ] `Resource` enum extended; `MODEL_RESOURCE_MAP` extended; views
      declare `resource` + `action`
- [ ] Services use `BaseService[T]`, per-call instantiation
- [ ] Repositories own write locks
- [ ] Exceptions subclass typed bases; `AppConfig.ready()` registers
      status codes
- [ ] External calls wrapped with `@resilient("name")` and registered
- [ ] Tasks routed in `CELERY_TASK_ROUTES`
- [ ] Cascade overrides propagate `user=`
- [ ] Schemas live under `apps/my_app/api_schemas/`, reuse core helpers
- [ ] Tests cover services, repository locks, and at least one
      end-to-end view path
