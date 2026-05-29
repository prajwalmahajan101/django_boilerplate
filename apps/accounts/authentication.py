"""API key authentication backend for DRF."""

import secrets

from django.core.cache import caches
from django.utils import timezone
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


class APIKeyAuthentication(BaseAuthentication):
    """Authenticate requests via the ``X-API-Key`` header.

    Looks up the key by its 8-char prefix, decrypts the stored key,
    and performs a constant-time comparison. Sets ``request.auth``
    to the ``APIKey`` instance on success.
    """

    def authenticate(self, request):
        # Function-local import is load-bearing: this class is referenced
        # from DRF's DEFAULT_AUTHENTICATION_CLASSES, so DRF settings resolve
        # it at app-registry population time — before accounts.models has
        # finished initializing. Module-level `from accounts.models import
        # APIKey` triggers a partial-init ImportError at Django boot.
        from accounts.models import APIKey

        key = request.META.get("HTTP_X_API_KEY")
        if not key:
            return None

        if len(key) < 8:
            raise AuthenticationFailed("Invalid API key.")

        prefix = key[:8]
        api_key = (
            APIKey.objects.select_related("user")
            .filter(prefix=prefix, is_active=True, revoked_at__isnull=True)
            .first()
        )

        if not api_key or not secrets.compare_digest(api_key.secret, key):
            raise AuthenticationFailed("Invalid API key.")

        if not api_key.user.is_active:
            raise AuthenticationFailed("User account is disabled.")

        # Debounce last_used_at on the rate_limit cache alias. Pinning the
        # alias keeps this isolated from the default cache so worker-only
        # deployments (which may swap the default backend) don't silently
        # break the debounce.
        debounce_cache = caches["rate_limit"]
        cache_key = f"apikey_used_{api_key.pk}"
        if not debounce_cache.get(cache_key):
            APIKey.objects.filter(pk=api_key.pk).update(last_used_at=timezone.now())
            debounce_cache.set(cache_key, True, timeout=300)

        return (api_key.user, api_key)

    def authenticate_header(self, request):
        return "X-API-Key"


class APIKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    """Registers ``APIKeyAuthentication`` as an OpenAPI security scheme.

    drf-spectacular discovers this class automatically when the
    ``accounts.authentication`` module is imported at startup.
    """

    target_class = "accounts.authentication.APIKeyAuthentication"
    name = "apiKeyAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": (
                "API key issued per service account. "
                "Pass the raw key in the ``X-API-Key`` header."
            ),
        }
