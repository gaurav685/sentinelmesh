"""Dependency wiring for simulation-service."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request

from sm_common.bus import EventBusProducer
from sm_common.config import AppSettings
from sm_common.db import Database
from sm_common.errors import Unauthenticated
from sm_common.observability import Metrics
from sm_common.security import InternalPrincipal, verify_internal_token

from .metrics import SimulationMetrics
from .repository import DecoyRepository
from .version import SERVICE_NAME

__all__ = ["Services", "get_decoy_repository", "get_principal", "get_services"]


@dataclass
class Services:
    settings: AppSettings
    metrics: Metrics
    sim_metrics: SimulationMetrics
    db: Database
    decoy_repo: DecoyRepository
    #: None when the event bus is disabled — `feed_pipeline` requests are then
    #: refused with a clear reason rather than silently doing nothing.
    producer: EventBusProducer | None


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


def get_decoy_repository(services: Services = Depends(get_services)) -> DecoyRepository:
    return services.decoy_repo


def get_principal(
    request: Request, services: Services = Depends(get_services)
) -> InternalPrincipal:
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
