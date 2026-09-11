"""`GET /api/v1/sim/twin` and `POST /api/v1/sim/twin/blast-radius`.

Internal-JWT only. The twin is read off the same synthetic environment a
scenario runs against — never a real asset inventory.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from sm_common.security import InternalPrincipal
from sm_contracts import BlastRadiusRequest, BlastRadiusResult, TwinSnapshot

from ..deps import get_principal
from ..twin import build_blast_radius, build_twin_snapshot
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/sim", tags=["simulation"])


@router.get("/twin", response_model=TwinSnapshot)
async def get_twin(
    seed: int = Query(default=1, ge=0),
    principal: InternalPrincipal = Depends(get_principal),
) -> TwinSnapshot:
    return build_twin_snapshot(seed)


@router.post("/twin/blast-radius", response_model=BlastRadiusResult)
async def post_blast_radius(
    req: BlastRadiusRequest,
    principal: InternalPrincipal = Depends(get_principal),
) -> BlastRadiusResult:
    return build_blast_radius(req)
