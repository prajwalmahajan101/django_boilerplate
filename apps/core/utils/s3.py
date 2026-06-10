"""S3 utilities: presigned URL generation, JSON fetching, and binary asset I/O."""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, BinaryIO
from urllib.parse import urlparse

from botocore.exceptions import BotoCoreError, ClientError
from core.exceptions.infrastructure import S3Exception, S3NotFoundError
from core.exceptions.repository import InvalidInputError
from core.utils.aws import get_aws_client
from core.utils.log_sanitization import safe_log_dict
from django.conf import settings
from resilience_kit import resilient

logger = logging.getLogger(__name__)


def parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    """Parse an ``s3://bucket/key`` URI into *(bucket, key)*."""
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise InvalidInputError(f"Invalid S3 URI format: {s3_uri}")

    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    if not key:
        raise InvalidInputError(f"S3 URI is missing object key: {s3_uri}")

    return bucket, key


def build_s3_uri(bucket: str, key: str) -> str:
    """Compose an ``s3://bucket/key`` URI. Pure helper, no I/O."""
    if not bucket or not key:
        raise InvalidInputError(
            f"Both bucket and key required (got bucket={bucket!r}, key={key!r})."
        )
    return f"s3://{bucket}/{key.lstrip('/')}"


_FILENAME_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def generate_object_key(prefix: str, filename: str, *, ext: str | None = None) -> str:
    """UUID-prefixed S3 key generator with date partition.

    Strips path components from filename and replaces unsafe chars. Returns
    e.g. ``assets/2026/04/<uuid>__cleaned-name.pdf``. Pure helper, no I/O.
    """
    base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].strip() or "file"
    cleaned = _FILENAME_SANITIZE_RE.sub("-", base).strip("-._") or "file"
    if ext and not cleaned.lower().endswith(f".{ext.lower().lstrip('.')}"):
        cleaned = f"{cleaned}.{ext.lstrip('.')}"
    now = datetime.now(UTC)
    folder = prefix.strip("/") or "assets"
    return f"{folder}/{now:%Y/%m}/{uuid.uuid4()}__{cleaned}"


@contextmanager
def _s3_call(operation: str, bucket: str, key: str) -> Iterator[None]:
    """Wrap an S3 client call: log + translate boto exceptions to S3Exception."""
    try:
        yield
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            # 404 = object absent (e.g. cache miss). Expected, not an infra
            # failure — see S3NotFoundError / the s3 breaker exclusion.
            raise S3NotFoundError(f"S3 object not found: {bucket}/{key}") from exc
        logger.error(
            "S3 %s failed",
            operation,
            extra=safe_log_dict(operation=operation, bucket=bucket, key=key, error=str(exc)),
            exc_info=True,
        )
        raise S3Exception(f"S3 {operation} failed for {bucket}/{key}") from exc
    except BotoCoreError as exc:
        logger.error(
            "S3 %s failed",
            operation,
            extra=safe_log_dict(operation=operation, bucket=bucket, key=key, error=str(exc)),
            exc_info=True,
        )
        raise S3Exception(f"S3 {operation} failed for {bucket}/{key}") from exc


@resilient("s3")
def generate_presigned_url(s3_uri: str, expiry: int | None = None) -> str:
    """Generate a presigned GET URL for an S3 object."""
    bucket, key = parse_s3_uri(s3_uri)
    expiry = expiry or getattr(settings, "S3_PRESIGNED_URL_EXPIRY", 3600)

    with _s3_call("generate_presigned_url", bucket, key):
        client = get_aws_client("s3")
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expiry,
        )


_DEFAULT_MAX_S3_JSON_SIZE = 10 * 1024 * 1024  # 10 MB


@resilient("s3")
def fetch_json_from_s3(s3_uri: str, max_size: int = _DEFAULT_MAX_S3_JSON_SIZE) -> dict[str, Any]:
    """Fetch a JSON file from S3 and return the parsed content."""
    bucket, key = parse_s3_uri(s3_uri)

    with _s3_call("fetch_json", bucket, key):
        client = get_aws_client("s3")
        response = client.get_object(Bucket=bucket, Key=key)
        content_length = response.get("ContentLength", 0)
        if content_length > max_size:
            raise S3Exception(
                f"S3 object too large ({content_length} bytes, max {max_size}): {bucket}/{key}"
            )
        body = response["Body"].read().decode("utf-8")

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        logger.error(
            "S3 object is not valid JSON",
            extra=safe_log_dict(bucket=bucket, key=key, error=str(exc)),
            exc_info=True,
        )
        raise S3Exception(f"S3 object is not valid JSON: {bucket}/{key}") from exc


@resilient("s3")
def fetch_bytes_from_s3(s3_uri: str, max_size: int) -> tuple[bytes, str]:
    """Fetch a binary object from S3.

    Returns ``(body_bytes, content_type)``. Used by the remark email builder
    when assembling MIME attachments. Raises :class:`S3Exception` if the
    object exceeds ``max_size`` so we never load oversized blobs into memory.
    """
    bucket, key = parse_s3_uri(s3_uri)
    with _s3_call("fetch_bytes", bucket, key):
        client = get_aws_client("s3")
        response = client.get_object(Bucket=bucket, Key=key)
        content_length = response.get("ContentLength", 0)
        if content_length > max_size:
            raise S3Exception(
                f"S3 object too large ({content_length} bytes, max {max_size}): {bucket}/{key}"
            )
        body = response["Body"].read()
        content_type = response.get("ContentType", "application/octet-stream")
        return body, content_type


@resilient("s3")
def upload_json_to_s3(data: dict[str, Any], bucket: str, key: str) -> str:
    """Serialize *data* as JSON and upload to S3."""
    body = json.dumps(data, ensure_ascii=False)
    with _s3_call("upload_json", bucket, key):
        client = get_aws_client("s3")
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json",
        )
    return build_s3_uri(bucket, key)


@resilient("s3")
def upload_file_to_s3(
    file_obj: BinaryIO,
    bucket: str,
    key: str,
    *,
    content_type: str,
    metadata: dict[str, str] | None = None,
) -> str:
    """Stream a file-like object to S3 (multipart-aware via upload_fileobj).

    ``file_obj`` must be a binary file-like object (e.g. Django's
    ``UploadedFile``). Returns the resulting ``s3://bucket/key`` URI.

    ``ContentLength`` is intentionally *not* exposed here: ``upload_fileobj``
    runs through the s3transfer manager whose ``ALLOWED_UPLOAD_ARGS``
    allowlist excludes it (the manager computes the length itself, and may
    switch to a multipart upload where a single ``ContentLength`` is
    meaningless). Passing it raises ``ValueError`` at call time.
    """
    extra_args: dict[str, Any] = {"ContentType": content_type}
    if metadata:
        extra_args["Metadata"] = {str(k): str(v) for k, v in metadata.items()}

    with _s3_call("upload_file", bucket, key):
        client = get_aws_client("s3")
        # upload_fileobj transparently switches to multipart for large files.
        client.upload_fileobj(file_obj, bucket, key, ExtraArgs=extra_args)
    return build_s3_uri(bucket, key)


@resilient("s3")
def delete_s3_object(s3_uri: str) -> None:
    """Delete an S3 object. Idempotent: missing keys are logged and swallowed.

    Intended for the future sweep job — not called by the v1 API.
    """
    bucket, key = parse_s3_uri(s3_uri)
    try:
        with _s3_call("delete", bucket, key):
            client = get_aws_client("s3")
            client.delete_object(Bucket=bucket, Key=key)
    except S3NotFoundError:
        # delete_object on a missing key returns 204 from S3, so a true
        # NoSuchKey is rare; if it surfaces, treat it as success.
        logger.info(
            "delete_s3_object: object already absent",
            extra=safe_log_dict(bucket=bucket, key=key),
        )


@resilient("s3")
def head_s3_object(s3_uri: str) -> dict[str, Any]:
    """Return metadata for an S3 object: size, content_type, etag, last_modified."""
    bucket, key = parse_s3_uri(s3_uri)
    with _s3_call("head", bucket, key):
        client = get_aws_client("s3")
        response = client.head_object(Bucket=bucket, Key=key)
        return {
            "size": response.get("ContentLength"),
            "content_type": response.get("ContentType"),
            "etag": response.get("ETag", "").strip('"'),
            "last_modified": response.get("LastModified"),
        }


def object_exists(s3_uri: str) -> bool:
    """Return True if the S3 object exists, False if it does not."""
    try:
        head_s3_object(s3_uri)
        return True
    except S3NotFoundError:
        return False
