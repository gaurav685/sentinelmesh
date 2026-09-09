"""ml-inference application factory (ADR-013).

An HTTP-only service: no Kafka consumer. `ModelHost` loads registered anomaly
models from `SM_ML_MODEL_DIR` lazily and serves typed inference. A missing model
is a typed `MODEL_UNAVAILABLE` (HTTP 503), never a 500 and never a fabricated
score.
"""

from __future__ import annotations

from fastapi import FastAPI

from sm_common.config import AppSettings, load_settings
from sm_common.fastapi import (
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    install_exception_handlers,
)
from sm_common.logging import configure_logging, get_logger
from sm_common.observability import build_metrics, configure_tracing
from sm_ml import ModelRegistry
from sm_ml.graph import GraphModelRegistry

from .deps import GraphModelHost, ModelHost, Services
from .metrics import InferenceMetrics
from .routes import health, infer, metrics
from .version import SERVICE_NAME, SERVICE_VERSION

__all__ = ["build_services", "create_app"]

_log = get_logger("sm.ml_inference")


def build_services(settings: AppSettings) -> Services:
    base_metrics = build_metrics(SERVICE_NAME)
    inference_metrics = InferenceMetrics(base_metrics, SERVICE_NAME)
    registry = ModelRegistry.from_env()
    host = ModelHost(registry, inference_metrics)
    graph_host = GraphModelHost(GraphModelRegistry.from_env(), inference_metrics)
    _log.info(
        "model_registry_scanned",
        service=SERVICE_NAME,
        registered=[r.name for r in host.catalog()],
        graph_registered=[r.name for r in graph_host.catalog()],
    )
    return Services(
        settings=settings,
        metrics=base_metrics,
        inference_metrics=inference_metrics,
        host=host,
        graph_host=graph_host,
    )


def create_app(
    settings: AppSettings | None = None, services: Services | None = None
) -> FastAPI:
    resolved_settings = settings or (services.settings if services else load_settings())
    configure_logging(resolved_settings)
    configure_tracing(resolved_settings)

    app = FastAPI(
        title="SentinelMesh ML Inference",
        version=SERVICE_VERSION,
        docs_url=None if resolved_settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if resolved_settings.is_production else "/openapi.json",
    )
    app.state.services = services or build_services(resolved_settings)
    app.add_middleware(SecurityHeadersMiddleware, hsts=resolved_settings.is_production)
    app.add_middleware(RequestContextMiddleware)
    install_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(infer.router)
    return app
