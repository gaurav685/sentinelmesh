"""Liveness, readiness, build metadata.

ai-analyst has no hard dependency: with no LLM key it degrades to the
deterministic template, so it is ready as soon as the process is up.
Postgres (Phase 14, req 33 — the `narrative` table) is a soft dependency
too: `POST /api/v1/analyst/explain`, `/hunt/*`, and `/agents/*` need no
database at all, only `GET .../narrative` does. `/readyz` reports whether
a live LLM provider is configured and whether Postgres is reachable, but
`ready` never turns `false` on Postgres alone.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from sm_common.observability import evaluate_readiness, liveness, probe_check
from sm_contracts import DepStatus, HealthResponse, MetaResponse, ReadyResponse

from ..deps import Services, get_services
from ..version import API_PREFIX, SERVICE_NAME, SERVICE_VERSION

__all__ = ["router"]

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return liveness(SERVICE_NAME, SERVICE_VERSION)


@router.get("/readyz", response_model=ReadyResponse)
async def readyz(services: Services = Depends(get_services)) -> ReadyResponse:
    mode = "live-capable" if services.llm_live_capable else "template-only"
    result = await evaluate_readiness([probe_check("postgres", services.db, required=False)])
    return ReadyResponse(
        ready=True,
        dependencies=[
            DepStatus(name="llm_provider", healthy=True, detail=mode),
            *result.dependencies,
        ],
    )


@router.get(f"{API_PREFIX}/meta", response_model=MetaResponse)
async def meta(services: Services = Depends(get_services)) -> MetaResponse:
    return MetaResponse(
        api_version=API_PREFIX.rsplit("/", 1)[-1],
        service=SERVICE_NAME,
        build=SERVICE_VERSION,
        environment=services.settings.env.value,
    )
