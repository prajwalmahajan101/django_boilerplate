"""API key authentication backend for DRF."""

import secrets

from django.core.cache import cache
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

        if not api_key or not secrets.compare_digest(api_key.encrypted_key, key):
            raise AuthenticationFailed("Invalid API key.")

        if not api_key.user.is_active:
            raise AuthenticationFailed("User account is disabled.")

        # Debounce last_used_at — write at most once per 5 minutes to
        # avoid a DB write on every request for high-throughput API keys.
        cache_key = f"apikey_used_{api_key.pk}"
        if not cache.get(cache_key):
            APIKey.objects.filter(pk=api_key.pk).update(last_used_at=timezone.now())
            cache.set(cache_key, True, timeout=300)

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
