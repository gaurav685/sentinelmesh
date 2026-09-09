"""Dependency wiring for graph-service.

The consumer loop the lifespan owns does the writing. The HTTP surface is
health / metrics plus the internal, service-JWT-guarded graph-query API — every
query is scoped to the tenant in the verified token, never a request field.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request

from sm_common.bus import EventBusConsumer, EventBusProducer, RecordProcessor
from sm_common.config import AppSettings
from sm_common.errors import Unauthenticated
from sm_common.graph import Graph
from sm_common.observability import Metrics
from sm_common.security import InternalPrincipal, verify_internal_token

from .engine import GraphEngine
from .metrics import GraphMetrics
from .repository import GraphRepository
from .version import SERVICE_NAME

__all__ = ["Services", "get_principal", "get_repository", "get_services"]


@dataclass
class Services:
    settings: AppSettings
    metrics: Metrics
    graph_metrics: GraphMetrics
    graph: Graph
    repository: GraphRepository
    producer: EventBusProducer
    consumer: EventBusConsumer
    engine: GraphEngine
    processor: RecordProcessor


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


def get_repository(services: Services = Depends(get_services)) -> GraphRepository:
    return services.repository


def get_principal(
    request: Request, services: Services = Depends(get_services)
) -> InternalPrincipal:
    """Verify the internal service JWT (`Authorization: Bearer …`). The query API
    is internal-only — reached through `api-gateway`, never the browser."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        services.metrics.authn_failures.labels(SERVICE_NAME, "no_bearer_token").inc()
        raise Unauthenticated()
    try:
        return verify_internal_token(
            token,
            signing_keys=[services.settings.internal_jwt_signing_key.get_secret_value()],
            audience=SERVICE_NAME,
            leeway_seconds=services.settings.jwt_leeway_seconds,
        )
    except Unauthenticated:
        services.metrics.authn_failures.labels(SERVICE_NAME, "internal_token_invalid").inc()
        raise
