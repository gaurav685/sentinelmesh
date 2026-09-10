"""ai-analyst application factory.

HTTP-only: no Kafka, no database. `api-gateway` gathers the evidence and calls
`POST /api/v1/analyst/explain`; the analyst runs the grounded LLM flow (or the
deterministic template when no provider key is configured) and returns an
`Explanation`. It holds no tools and performs no action.
"""

from __future__ import annotations

from fastapi import FastAPI

from sm_ai import AuditEvent, HttpLlmBoundary, LlmClient
from sm_common.config import AppSettings, load_settings
from sm_common.fastapi import (
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    install_exception_handlers,
)
from sm_common.logging import configure_logging, get_logger
from sm_common.observability import build_metrics, configure_tracing

from .agents import AgentRunner
from .analyst import IncidentAnalyst
from .deps import Services
from .metrics import AnalystMetrics
from .routes import agents, explain, health, metrics
from .version import SERVICE_NAME, SERVICE_VERSION

__all__ = ["build_services", "create_app"]

_log = get_logger("sm.ai_analyst")

_LIVE_PROVIDERS = frozenset({"anthropic", "openai", "local"})


def build_services(settings: AppSettings) -> Services:
    base_metrics = build_metrics(SERVICE_NAME)
    analyst_metrics = AnalystMetrics(base_metrics, SERVICE_NAME)

    def _llm_audit(ev: AuditEvent) -> None:
        _log.info(
            "llm_call",
            purpose=ev.purpose,
            provider=ev.provider,
            outcome=ev.outcome,
            attempt=ev.attempt,
            prompt_sha256=ev.prompt_sha256,
            latency_ms=ev.latency_ms,
        )

    def _analyst_event(name: str) -> None:
        _log.warning("analyst_event", detail=name)

    live_capable = bool(settings.llm_api_key) and settings.llm_default_provider in _LIVE_PROVIDERS
    llm: LlmClient | None = None
    if live_capable:
        provider = HttpLlmBoundary(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            provider_name=settings.llm_default_provider,
        )
        llm = LlmClient(
            provider=provider,
            max_prompt_tokens=settings.llm_max_prompt_tokens,
            timeout_s=float(settings.llm_request_timeout_s),
            max_retries=settings.llm_max_retries,
            audit_sink=_llm_audit,
        )

    model = settings.llm_default_model or "unset"
    analyst = IncidentAnalyst(
        llm, model=model, max_output_tokens=settings.llm_max_output_tokens, audit=_analyst_event
    )
    agent_runner = AgentRunner(llm, model=model, settings=settings)
    _log.info(
        "service_start",
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
        analyst_mode="live-capable" if live_capable else "template-only",
        provider=settings.llm_default_provider,
    )
    return Services(
        settings=settings,
        metrics=base_metrics,
        analyst_metrics=analyst_metrics,
        analyst=analyst,
        agent_runner=agent_runner,
        llm_live_capable=live_capable,
    )


def create_app(
    settings: AppSettings | None = None, services: Services | None = None
) -> FastAPI:
    resolved_settings = settings or (services.settings if services else load_settings())
    configure_logging(resolved_settings)
    configure_tracing(resolved_settings)

    app = FastAPI(
        title="SentinelMesh AI Analyst",
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
    app.include_router(explain.router)
    app.include_router(agents.router)
    return app
