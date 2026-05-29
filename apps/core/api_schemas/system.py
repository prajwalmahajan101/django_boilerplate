"""``extend_schema`` decorators for system endpoints (health, readiness).

Imported by ``apps/core/views.py``. Kept separate from the cross-cutting
response objects in ``responses.py`` because these are full endpoint
schemas, not reusable building blocks.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema

health_schema = extend_schema(
    operation_id="system_health",
    summary="Service health check",
    description=(
        "Lightweight health probe for load balancers. Returns 200 when the "
        "database is reachable, 503 otherwise. Staff users additionally "
        "receive a ``checks`` map with component-level status."
    ),
    tags=["System"],
    responses={
        200: OpenApiResponse(
            description="Service is healthy.",
            response={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "healthy"},
                    "checks": {
                        "type": "object",
                        "nullable": True,
                        "properties": {
                            "database": {"type": "string", "example": "connected"},
                        },
                    },
                },
            },
            examples=[
                OpenApiExample(
                    name="healthy",
                    value={"status": "healthy"},
                ),
                OpenApiExample(
                    name="healthy_staff",
                    value={
                        "status": "healthy",
                        "checks": {"database": "connected"},
                    },
                    description="Response seen by staff users.",
                ),
            ],
        ),
        503: OpenApiResponse(
            description="Service is unhealthy — database unreachable.",
            response={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "unhealthy"},
                },
            },
            examples=[
                OpenApiExample(
                    name="unhealthy",
                    value={"status": "unhealthy"},
                ),
            ],
        ),
    },
)


readiness_schema = extend_schema(
    operation_id="system_readiness",
    summary="Service readiness check",
    description=(
        "Readiness probe for orchestration systems (Kubernetes, ECS). "
        "Checks database, Valkey cache, and Celery broker connectivity. "
        "Returns 200 when all dependencies are reachable, 503 otherwise. "
        "Staff users additionally receive a ``checks`` map."
    ),
    tags=["System"],
    responses={
        200: OpenApiResponse(
            description="All dependencies are reachable.",
            response={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "ready"},
                    "checks": {
                        "type": "object",
                        "nullable": True,
                        "properties": {
                            "database": {"type": "string", "example": "connected"},
                            "cache": {"type": "string", "example": "connected"},
                            "celery_broker": {"type": "string", "example": "connected"},
                        },
                    },
                },
            },
            examples=[
                OpenApiExample(
                    name="ready",
                    value={"status": "ready"},
                ),
                OpenApiExample(
                    name="ready_staff",
                    value={
                        "status": "ready",
                        "checks": {
                            "database": "connected",
                            "cache": "connected",
                            "celery_broker": "connected",
                        },
                    },
                ),
            ],
        ),
        503: OpenApiResponse(
            description="One or more dependencies are unreachable.",
            response={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "not_ready"},
                },
            },
            examples=[
                OpenApiExample(
                    name="not_ready",
                    value={"status": "not_ready"},
                ),
            ],
        ),
    },
)
