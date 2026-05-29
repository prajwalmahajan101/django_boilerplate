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
        from core.enums import Resource
        from core.exceptions.handler import register_exception_mapping
        from core.rbac_registry import register_resource

        register_exception_mapping(
            NoFieldsToUpdateError, status.HTTP_400_BAD_REQUEST
        )
        register_exception_mapping(
            InvalidTimezoneError, status.HTTP_400_BAD_REQUEST
        )
        register_exception_mapping(
            APIKeyGenerationError, status.HTTP_500_INTERNAL_SERVER_ERROR
        )

        # RBAC: this used to be RBACBackend.MODEL_RESOURCE_MAP, a hardcoded
        # dict in apps/accounts/backends.py. Moving the registration here
        # means a new domain app drops in next to accounts/ and registers
        # its own resources from its own AppConfig.ready() — no edit to
        # the auth backend required.
        register_resource("accounts.user", Resource.ACCOUNT)
        register_resource("accounts.role", Resource.ROLE)
        register_resource("accounts.permission", Resource.ROLE)
        register_resource("accounts.apikey", Resource.API_KEY)
