"""Contract: ``BaseService.list`` hides soft-deleted rows by default.

ISSUE-018 — without this, a casually written listing endpoint that
forgets ``active_only=True`` silently surfaces soft-deleted rows to
API consumers. Default-deny is the fail-safe.
"""

from __future__ import annotations

from accounts.models import APIKey
from core.base.service import BaseService


class _APIKeyService(BaseService[APIKey]):
    model = APIKey


def _valid_payload(user, *, name="ci-key", prefix="abcdef12") -> dict:
    return {
        "user": user,
        "name": name,
        "prefix": prefix,
        "secret": "x" * 32,
    }


def test_list_hides_soft_deleted_by_default(user):
    svc = _APIKeyService()
    live = svc.create(_valid_payload(user, name="live", prefix="aaaaaaaa"))
    soft = svc.create(_valid_payload(user, name="soft", prefix="bbbbbbbb"))
    svc.delete(soft.pk, soft=True, user=user)

    ids = {k.pk for k in svc.list()}
    assert live.pk in ids
    assert soft.pk not in ids


def test_list_active_only_false_returns_soft_deleted(user):
    svc = _APIKeyService()
    live = svc.create(_valid_payload(user, name="live2", prefix="cccccccc"))
    soft = svc.create(_valid_payload(user, name="soft2", prefix="dddddddd"))
    svc.delete(soft.pk, soft=True, user=user)

    ids = {k.pk for k in svc.list(active_only=False)}
    assert live.pk in ids
    assert soft.pk in ids


def test_list_active_alias_matches_default(user):
    """The list_active() back-compat shim returns the same rows as list()."""
    svc = _APIKeyService()
    svc.create(_valid_payload(user, name="live3", prefix="eeeeeeee"))
    soft = svc.create(_valid_payload(user, name="soft3", prefix="ffffffff"))
    svc.delete(soft.pk, soft=True, user=user)

    assert {k.pk for k in svc.list()} == {k.pk for k in svc.list_active()}
