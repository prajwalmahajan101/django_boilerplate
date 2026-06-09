"""Tests for ``summarise_body_for_audit`` and ``serialize_error_body``."""

from __future__ import annotations

from core.api_log.sanitizers import (
    serialize_error_body,
    summarise_body_for_audit,
)
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import QueryDict
from django.test import SimpleTestCase, override_settings


class SummariseBodyForAuditTests(SimpleTestCase):
    def test_none_passes_through(self) -> None:
        self.assertIsNone(summarise_body_for_audit(None))

    def test_bytes_summarised(self) -> None:
        self.assertEqual(
            summarise_body_for_audit(b"hello"),
            {"__bytes__": True, "size_bytes": 5},
        )

    def test_dict_unchanged(self) -> None:
        self.assertEqual(summarise_body_for_audit({"a": 1}), {"a": 1})

    def test_querydict_with_uploaded_file(self) -> None:
        qd = QueryDict(mutable=True)
        qd["name"] = "John"
        upload = SimpleUploadedFile("doc.pdf", b"binarydata", content_type="application/pdf")
        qd.appendlist("doc", upload)
        result = summarise_body_for_audit(qd)
        self.assertTrue(result["__multipart__"])
        names = {f["name"] for f in result["fields"]}
        self.assertEqual(names, {"name", "doc"})
        file_entry = next(f for f in result["fields"] if f["name"] == "doc")
        self.assertEqual(file_entry["filename"], "doc.pdf")
        self.assertEqual(file_entry["content_type"], "application/pdf")
        self.assertEqual(file_entry["size_bytes"], 10)


class SerializeErrorBodyTests(SimpleTestCase):
    def test_none(self) -> None:
        self.assertIsNone(serialize_error_body(None))

    def test_string_passes_through(self) -> None:
        self.assertEqual(serialize_error_body("oops"), "oops")

    def test_dict_json_encoded(self) -> None:
        self.assertEqual(
            serialize_error_body({"error": "boom"}),
            '{"error": "boom"}',
        )

    def test_non_serialisable_falls_back_to_str(self) -> None:
        class X:
            def __str__(self) -> str:
                return "X-instance"

        out = serialize_error_body(X())
        self.assertIn("X-instance", out)

    @override_settings(API_LOG_MAX_BODY_LEN=10)
    def test_truncates_long_body(self) -> None:
        out = serialize_error_body("x" * 50)
        self.assertTrue(out.endswith("…[truncated]"))
