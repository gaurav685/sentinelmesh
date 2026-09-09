"""Internal MITRE ATT&CK API (service-JWT, audience `mitre-service`)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from sm_common.security import InternalPrincipal

from ..catalog import CatalogRepository
from ..deps import get_catalog, get_mapping, get_principal
from ..mapping import MappingEngine
from ..schemas import (
    HeatmapCellModel,
    HeatmapResponse,
    MapRequest,
    MapResponse,
    TechniquesResponse,
)
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/mitre", tags=["mitre"])


@router.get("/techniques", response_model=TechniquesResponse)
async def techniques(
    include_deprecated: bool = Query(default=False),
    _principal: InternalPrincipal = Depends(get_principal),
    catalog: CatalogRepository = Depends(get_catalog),
) -> TechniquesResponse:
    rows = await catalog.list_techniques(include_deprecated=include_deprecated)
    return TechniquesResponse(matrix=await catalog.latest_version(), count=len(rows), techniques=rows)


@router.post("/map", response_model=MapResponse)
async def map_techniques(
    req: MapRequest,
    principal: InternalPrincipal = Depends(get_principal),
    engine: MappingEngine = Depends(get_mapping),
) -> MapResponse:
    result = await engine.map_techniques(
        req.technique_ids, rationale=req.rationale, source=req.source, confidence=req.confidence
    )
    persisted = 0
    if req.persist:
        persisted = await engine.persist(
            tenant_id=principal.tenant_id,
            subject_type=req.subject_type,
            subject_id=req.subject_id,
            result=result,
        )
    return MapResponse(
        matrix_version=result.matrix_version, matches=result.matches,
        unmapped=result.unmapped, persisted=persisted,
    )


@router.get("/heatmap", response_model=HeatmapResponse)
async def heatmap(
    principal: InternalPrincipal = Depends(get_principal),
    engine: MappingEngine = Depends(get_mapping),
    catalog: CatalogRepository = Depends(get_catalog),
) -> HeatmapResponse:
    cells = await engine.heatmap(principal.tenant_id)
    version = await catalog.latest_version()
    return HeatmapResponse(
        matrix_version=version.version if version else None,
        cells=[
            HeatmapCellModel(
                technique_id=c.technique_id, name=c.name, tactic_id=c.tactic_id,
                subject_count=c.subject_count,
            )
            for c in cells
        ],
    )
