"""Unit tests for ``core.utils.log_sanitization``.

Covers the redaction / truncation / depth-guard branches in
``sanitize_for_log`` and its helpers, plus the public ``safe_log_dict``
and ``truncate_for_log`` helpers.
"""

from __future__ import annotations

import pytest
from core.utils.log_sanitization import (
    safe_log_dict,
    sanitize_for_log,
    truncate_for_log,
)
from django.test import override_settings


# ---------- top-level switches -------------------------------------------


@override_settings(LOG_SANITIZATION={"SANITIZE_ENABLED": False})
def test_returns_value_untouched_when_disabled():
    payload = {"password": "secret"}
    assert sanitize_for_log(payload) is payload


def test_none_passes_through_unchanged():
    assert sanitize_for_log(None) is None


def test_bool_passes_through_unchanged():
    assert sanitize_for_log(True) is True
    assert sanitize_for_log(False) is False


def test_int_and_float_pass_through_unchanged():
    assert sanitize_for_log(42) == 42
    assert sanitize_for_log(3.14) == 3.14


def test_bytes_summarised_not_inlined():
    out = sanitize_for_log(b"hello world!")
    assert out == "<bytes: 12 bytes>"


def test_unknown_object_falls_back_to_repr():
    class Foo:
        def __str__(self):  # noqa: D401
            return "foo-repr"

    assert sanitize_for_log(Foo()) == "foo-repr"


def test_unknown_object_with_failing_str_returns_unserializable_marker():
    class Bad:
        def __str__(self):
            raise RuntimeError("boom")

    out = sanitize_for_log(Bad())
    assert out == "<Bad: unserializable>"


# ---------- depth guard ---------------------------------------------------


def test_max_depth_returns_marker():
    # Nest dicts 7 deep; default max_depth is 5.
    nested = current = {}
    for _ in range(7):
        current["nested"] = {}
        current = current["nested"]
    current["leaf"] = "ok"
    out = sanitize_for_log(nested)
    # Walk down and find the marker.
    cursor = out
    for _ in range(6):
        cursor = cursor["nested"]
    assert cursor == "<max depth exceeded>"


# ---------- string sanitisation ------------------------------------------


def test_string_escapes_control_characters():
    out = sanitize_for_log("line1\nline2\ttab\rreturn\\backslash")
    assert "\\n" in out
    assert "\\t" in out
    assert "\\r" in out
    assert "\\\\" in out


def test_string_escapes_low_control_bytes_with_hex():
    out = sanitize_for_log("\x01abc\x07")
    assert "\\x01" in out
    assert "\\x07" in out


def test_long_string_truncated_with_marker():
    out = sanitize_for_log("a" * 500)
    assert "..." in out
    assert "(500 chars)" in out


# ---------- dict sanitisation --------------------------------------------


def test_sensitive_keys_are_masked():
    # "auth" matches the SENSITIVE_PATTERN but isn't in EXCLUDED_FIELDS.
    out = sanitize_for_log({"auth": "hunter2", "username": "alice"})
    assert out["auth"] == "***REDACTED***"
    assert out["username"] == "alice"


def test_sensitive_pattern_case_insensitive_match():
    out = sanitize_for_log({"AuthHeader": "x", "JwtToken": "y"})
    assert out["AuthHeader"] == "***REDACTED***"
    assert out["JwtToken"] == "***REDACTED***"


@override_settings(LOG_SANITIZATION={"EXCLUDED_FIELDS": frozenset({"drop_me"})})
def test_excluded_fields_removed_entirely():
    out = sanitize_for_log({"drop_me": 1, "keep": 2})
    assert "drop_me" not in out
    assert out["keep"] == 2


def test_dict_truncated_after_max_keys():
    payload = {f"k{i}": i for i in range(30)}
    out = sanitize_for_log(payload, max_dict_keys=5)
    # 5 entries + the truncation marker
    assert len(out) == 6
    assert out["__truncated__"] == "25 more keys"


# ---------- iterable sanitisation ----------------------------------------


@pytest.mark.parametrize("ctor", [list, tuple, set, frozenset])
def test_iterables_normalise_to_list(ctor):
    out = sanitize_for_log(ctor([1, 2, 3]))
    assert isinstance(out, list)
    assert sorted(out) == [1, 2, 3]


def test_iterable_truncated_after_max_items():
    out = sanitize_for_log(list(range(20)), max_list_items=5)
    assert len(out) == 6
    assert out[-1] == "...and 15 more items"


# ---------- public helpers -----------------------------------------------


def test_safe_log_dict_forwards_kwargs_and_sanitises():
    out = safe_log_dict(auth="secret", user="alice")
    assert out == {"auth": "***REDACTED***", "user": "alice"}


def test_truncate_for_log_returns_short_string_unchanged():
    assert truncate_for_log("hi") == "hi"


def test_truncate_for_log_truncates_long_string():
    out = truncate_for_log("x" * 500, max_length=80)
    assert "..." in out
    assert "(500 chars)" in out


def test_truncate_for_log_coerces_non_string():
    out = truncate_for_log(12345, max_length=2)
    assert "..." in out
    assert out.endswith("(5 chars)")
