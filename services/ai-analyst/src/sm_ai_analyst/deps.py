"""Dependency wiring for ai-analyst."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request

from sm_common.config import AppSettings
from sm_common.errors import Unauthenticated
from sm_common.observability import Metrics
from sm_common.security import InternalPrincipal, verify_internal_token

from .agents import AgentRunner
from .analyst import IncidentAnalyst
from .metrics import AnalystMetrics
from .version import SERVICE_NAME

__all__ = ["Services", "get_agent_runner", "get_analyst", "get_principal", "get_services"]


@dataclass
class Services:
    settings: AppSettings
    metrics: Metrics
    analyst_metrics: AnalystMetrics
    analyst: IncidentAnalyst
    agent_runner: AgentRunner
    #: True when a real provider key is configured; False = template-only.
    llm_live_capable: bool


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


def get_analyst(services: Services = Depends(get_services)) -> IncidentAnalyst:
    return services.analyst


def get_agent_runner(services: Services = Depends(get_services)) -> AgentRunner:
    return services.agent_runner


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
