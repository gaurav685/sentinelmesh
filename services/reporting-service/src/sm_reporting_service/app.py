"""reporting-service application factory.

HTTP-triggered, not a Kafka consumer: `POST /api/v1/reports` gathers content
from `detection-engine` (direct Postgres read), `graph-service`,
`mitre-service`, `ai-analyst`, and `memory-service` (internal HTTP), renders
a PDF, uploads it to S3-compatible object storage (ADR-019), persists the
result, and produces `report.generated`. The lifespan owns the DB pool, the
HTTP client, the object-store bucket setup, and the Kafka producer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from sm_common.bus import EventBusProducer
from sm_common.config import AppSettings, load_settings
from sm_common.db import Database
from sm_common.fastapi import (
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    TracingMiddleware,
    install_exception_handlers,
)
from sm_common.logging import configure_logging, get_logger
from sm_common.objectstore import ObjectStore
from sm_common.observability import build_metrics, configure_tracing, shutdown_tracing

from .content_client import ContentClient
from .content_repository import ContentRepository
from .deps import Services
from .generator import ReportGenerator
from .metrics import ReportMetrics
from .repository import ReportRepository
from .routes import health, metrics, reports
from .version import SERVICE_NAME, SERVICE_VERSION

__all__ = ["build_services", "create_app"]

_log = get_logger("sm.reporting_service")


def build_services(settings: AppSettings) -> Services:
    base_metrics = build_metrics(SERVICE_NAME)
    report_metrics = ReportMetrics(base_metrics, SERVICE_NAME)
    db = Database.from_settings(settings)
    repo = ReportRepository(db)
    content_repo = ContentRepository(db)
    http = httpx.AsyncClient(timeout=15.0)
    content = ContentClient(
        http, signing_key=settings.internal_jwt_signing_key.get_secret_value(),
        graph_url=settings.graph_service_url, mitre_url=settings.mitre_service_url,
        ai_analyst_url=settings.ai_analyst_url, memory_url=settings.memory_service_url,
    )
    store = ObjectStore.from_settings(settings)
    producer = EventBusProducer.from_settings(settings, metrics=base_metrics)
    generator = ReportGenerator(
        repo=repo, content_repo=content_repo, content=content, store=store, producer=producer,
        metrics=report_metrics, bucket=settings.s3_bucket_reports,
    )
    return Services(
        settings=settings, metrics=base_metrics, report_metrics=report_metrics, db=db, repo=repo,
        http=http, content_repo=content_repo, content=content, store=store, producer=producer,
        generator=generator,
    )


def create_app(
    settings: AppSettings | None = None, services: Services | None = None
) -> FastAPI:
    resolved_settings = settings or (services.settings if services else load_settings())
    configure_logging(resolved_settings)
    configure_tracing(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owns = services is None
        svc = services or build_services(resolved_settings)
        app.state.services = svc

        if owns:
            await svc.producer.start()
            try:
                await svc.store.ensure_bucket(resolved_settings.s3_bucket_reports)
            except Exception as exc:
                _log.warning("object_storage_bucket_setup_failed", error=str(exc))
        _log.info("service_start", service=SERVICE_NAME, version=SERVICE_VERSION)
        try:
            yield
        finally:
            if owns:
                await svc.producer.stop()
                await svc.http.aclose()
                await svc.db.dispose()
            shutdown_tracing()
            _log.info("service_stop", service=SERVICE_NAME)

    app = FastAPI(
        title="SentinelMesh Reporting Service",
        version=SERVICE_VERSION,
        lifespan=lifespan,
        docs_url=None if resolved_settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if resolved_settings.is_production else "/openapi.json",
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=resolved_settings.is_production)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(TracingMiddleware)
    install_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(reports.router)
    return app
