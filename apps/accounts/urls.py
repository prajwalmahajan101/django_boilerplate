"""URL configuration for auth endpoints."""

from django.urls import path

from accounts.views import (
    APIKeyDeleteView,
    APIKeyRevokeView,
    GoogleLogin,
    logout,
    me,
    token_refresh,
)

app_name = "accounts"

urlpatterns = [
    path("google/", GoogleLogin.as_view(), name="google-login"),
    path("token/refresh/", token_refresh, name="token-refresh"),
    path("logout/", logout, name="auth-logout"),
    path("me/", me, name="auth-me"),
    path("api-keys/<int:pk>/", APIKeyDeleteView.as_view(), name="api-key-delete"),
    # Soft-revoke: keeps audit history; auth backend rejects on next use.
    path("api-keys/<int:pk>/revoke/", APIKeyRevokeView.as_view(), name="api-key-revoke"),
]
