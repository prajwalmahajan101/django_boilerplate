"""Shared AWS client provider with thread-local singletons.

Provides a single ``get_aws_client`` function that returns a boto3 client
for any AWS service, cached per (service, region) per thread. This mirrors
the thread-local pattern used in ``core/utils/s3.py`` and
``core/utils/http_client.py``, but is reusable across all AWS services.

Usage::

    from core.utils.aws import get_aws_client

    s3  = get_aws_client("s3")
    ses = get_aws_client("ses", region="us-east-1")
"""

from __future__ import annotations

import threading

import boto3
from django.conf import settings

_thread_local = threading.local()


def get_aws_client(service_name: str, *, region: str | None = None):
    """Return a thread-local boto3 client for *service_name*.

    Clients are cached per (service_name, region) per thread — one client
    instance is created on the first call and reused on subsequent calls
    from the same thread.

    Args:
        service_name: AWS service identifier (e.g. ``"s3"``, ``"ses"``).
        region: AWS region name. Defaults to ``settings.AWS_REGION``
            (itself defaulting to ``"ap-south-1"``). Pass an explicit
            region only when the service must be in a different region
            from the application default.

    Returns:
        A ``botocore.client.<ServiceName>`` instance. Credentials are
        resolved from the boto3 default chain (environment variables,
        instance profile, ``~/.aws/credentials``).
    """
    resolved_region = region or getattr(settings, "AWS_REGION", "ap-south-1")

    # Region names contain hyphens (e.g. "ap-south-1") which are not valid
    # in Python attribute names, so replace them before building the key.
    cache_key = f"_aws_{service_name}_{resolved_region}".replace("-", "_")

    client = getattr(_thread_local, cache_key, None)
    if client is None:
        client = boto3.client(service_name, region_name=resolved_region)
        setattr(_thread_local, cache_key, client)
    return client
