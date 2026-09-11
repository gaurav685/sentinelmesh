"""Dependency wiring for reporting-service."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from fastapi import Depends, Request

from sm_common.bus import EventBusProducer
from sm_common.config import AppSettings
from sm_common.db import Database
from sm_common.errors import Unauthenticated
from sm_common.objectstore import ObjectStore
from sm_common.observability import Metrics
from sm_common.security import InternalPrincipal, verify_internal_token

from .content_client import ContentClient
from .content_repository import ContentRepository
from .generator import ReportGenerator
from .metrics import ReportMetrics
from .repository import ReportRepository
from .version import SERVICE_NAME

__all__ = ["Services", "get_generator", "get_principal", "get_repository", "get_services"]


@dataclass
class Services:
    settings: AppSettings
    metrics: Metrics
    report_metrics: ReportMetrics
    db: Database
    repo: ReportRepository
    http: httpx.AsyncClient
    content_repo: ContentRepository
    content: ContentClient
    store: ObjectStore
    producer: EventBusProducer
    generator: ReportGenerator


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


def get_repository(services: Services = Depends(get_services)) -> ReportRepository:
    return services.repo


def get_generator(services: Services = Depends(get_services)) -> ReportGenerator:
    return services.generator


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
