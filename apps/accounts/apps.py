from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # Register domain exception → HTTP status mappings here so the
        # core handler stays free of domain-app imports (see apps/core/CLAUDE.md
        # boundary rule: "Nothing in core imports from domain apps").
        from rest_framework import status

        from accounts.exceptions import (
            APIKeyGenerationError,
            InvalidTimezoneError,
            NoFieldsToUpdateError,
        )
        from core.exceptions.handler import register_exception_mapping

        register_exception_mapping(
            NoFieldsToUpdateError, status.HTTP_400_BAD_REQUEST
        )
        register_exception_mapping(
            InvalidTimezoneError, status.HTTP_400_BAD_REQUEST
        )
        register_exception_mapping(
            APIKeyGenerationError, status.HTTP_500_INTERNAL_SERVER_ERROR
        )
