"""``ApiLog`` — one row per inbound request / outbound HTTP call.

The audit pipeline (see :mod:`core.api_log.dispatch`) writes through
the configured backend; this is the storage model. Headers, body, and
error payloads are stored as JSON columns and are expected to have
been redacted/truncated by :mod:`core.api_log.sanitizers` before
landing here.
"""

from __future__ import annotations

import uuid

from django.db import models


class Direction(models.TextChoices):
    """Whether the audited HTTP call was inbound or outbound."""

    INBOUND = "inbound", "Inbound"
    OUTBOUND = "outbound", "Outbound"


class ApiLog(models.Model):
    """One audited HTTP call.

    ``ttl_expires_at`` is a hint for a downstream pruning job; ``None``
    means "no expiry / keep forever". The same row schema is shared by
    inbound and outbound — ``direction`` disambiguates.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    direction = models.CharField(max_length=16, choices=Direction.choices)
    service_name = models.CharField(max_length=128)
    request_id = models.CharField(max_length=128, db_index=True)
    method = models.CharField(max_length=16)
    url = models.TextField()
    status_code = models.IntegerField(null=True, blank=True)
    duration_ms = models.FloatField(null=True, blank=True)
    request_headers = models.JSONField(default=dict, blank=True)
    request_body = models.TextField(null=True, blank=True)
    response_headers = models.JSONField(default=dict, blank=True)
    response_body = models.TextField(null=True, blank=True)
    error = models.JSONField(null=True, blank=True)
    extra = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ttl_expires_at = models.IntegerField(null=True, blank=True)

    class Meta:
        app_label = "api_log"
        db_table = "api_logs"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["service_name", "created_at"]),
            models.Index(fields=["direction", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"<ApiLog {self.direction} {self.method} {self.url} -> {self.status_code}>"
