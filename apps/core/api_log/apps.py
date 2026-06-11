"""``api_log`` Django app config."""

from django.apps import AppConfig


class ApiLogConfig(AppConfig):
    """Django app config for ``api_log`` — initialises the persistence backend on ready."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "core.api_log"
    label = "api_log"
    verbose_name = "API audit log"

    def ready(self) -> None:
        # Resolve and cache the persistence backend so the first request
        # does not pay the import cost. Backend selection is driven by
        # ``API_LOG_BACKEND`` (default ``orm``).
        from core.api_log import factory

        factory.init_repository()
