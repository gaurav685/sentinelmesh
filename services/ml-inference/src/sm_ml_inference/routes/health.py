"""Liveness, readiness, build metadata.

`ml-inference` has no hard external dependency: models are optional artifacts and
the caller degrades when one is missing (ADR-013). So `/readyz` is ready as soon
as the process is up; it reports the registered catalog and what is loaded so an
operator can see whether artifacts are present.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from sm_common.observability import liveness
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
    catalog = services.host.catalog()
    loaded = services.host.loaded()
    graph_catalog = services.graph_host.catalog()
    return ReadyResponse(
        ready=True,  # models are optional; the caller degrades when one is missing
        dependencies=[
            DepStatus(
                name="models",
                healthy=True,
                detail=f"{len(catalog)} registered, {len(loaded)} loaded",
            ),
            DepStatus(
                name="graph_models",
                healthy=True,
                detail=f"{len(graph_catalog)} registered + structural (builtin)",
            ),
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
