"""Internal graph-query API (Phase 4 Unit 3).

Read-only. Every query is scoped to `principal.tenant_id` (from the verified
internal JWT), parameterized, depth-bounded and row-capped by the repository.
No endpoint accepts raw Cypher.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from sm_common.errors import NotFound
from sm_common.security import InternalPrincipal
from sm_contracts import HuntResult, QueryPlan

from ..deps import Services, get_hunt_runner, get_principal, get_repository, get_services
from ..hunt import HuntRunner
from ..intel import analyse_neighbourhood
from ..repository import GraphRepository
from ..schemas import (
    EntityResponse,
    GraphIntelResponse,
    GraphNodeModel,
    NeighborsResponse,
    PathResponse,
)
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/graph", tags=["graph-query"])


@router.get("/entity", response_model=EntityResponse)
async def entity(
    label: str = Query(description="Node label, e.g. ':Host' or 'Host'."),
    key: str = Query(description="The node's natural key value."),
    principal: InternalPrincipal = Depends(get_principal),
    repo: GraphRepository = Depends(get_repository),
) -> EntityResponse:
    node = await repo.entity(principal.tenant_id, label, key)
    if node is None:
        raise NotFound(f"{label} {key!r} not found")
    return EntityResponse(entity=GraphNodeModel.of(node))


@router.get("/neighbors", response_model=NeighborsResponse)
async def neighbors(
    label: str = Query(description="Root node label."),
    key: str = Query(description="Root node natural key value."),
    depth: int = Query(default=1, ge=1, description="Traversal depth (clamped to the server cap)."),
    limit: int | None = Query(default=None, ge=1, description="Row cap (clamped to the server cap)."),
    principal: InternalPrincipal = Depends(get_principal),
    repo: GraphRepository = Depends(get_repository),
) -> NeighborsResponse:
    view = await repo.neighbors(principal.tenant_id, label, key, depth=depth, limit=limit)
    return NeighborsResponse.of(depth, view)


@router.get("/intel", response_model=GraphIntelResponse)
async def intel(
    label: str = Query(description="Subject node label."),
    key: str = Query(description="Subject node natural key value."),
    depth: int = Query(default=2, ge=1, description="Neighbourhood depth (clamped to the server cap)."),
    principal: InternalPrincipal = Depends(get_principal),
    repo: GraphRepository = Depends(get_repository),
    services: Services = Depends(get_services),
) -> GraphIntelResponse:
    if await repo.entity(principal.tenant_id, label, key) is None:
        raise NotFound(f"{label} {key!r} not found")
    view = await repo.neighbors(principal.tenant_id, label, key, depth=depth)
    result = analyse_neighbourhood(
        view, label=label, key=key, z_threshold=services.settings.graph_anomaly_z
    )
    return GraphIntelResponse.of(result)


@router.get("/paths", response_model=PathResponse)
async def paths(
    src_label: str = Query(description="Source node label."),
    src_key: str = Query(description="Source node natural key value."),
    dst_label: str = Query(description="Destination node label."),
    dst_key: str = Query(description="Destination node natural key value."),
    max_depth: int = Query(default=4, ge=1, description="Max path length (clamped to the server cap)."),
    principal: InternalPrincipal = Depends(get_principal),
    repo: GraphRepository = Depends(get_repository),
) -> PathResponse:
    view = await repo.attack_path(
        principal.tenant_id, (src_label, src_key), (dst_label, dst_key), max_depth=max_depth
    )
    return PathResponse.of(view)


@router.post("/hunt", response_model=HuntResult)
async def hunt(
    plan: QueryPlan,
    principal: InternalPrincipal = Depends(get_principal),
    runner: HuntRunner = Depends(get_hunt_runner),
) -> HuntResult:
    """Execute a **validated** `QueryPlan`. `api-gateway` sends the plan (from a
    structured form or an `ai-analyst` NL translation); this endpoint validates
    it against the capability set, compiles it to one parameterized Cypher
    template, scopes it to `principal.tenant_id` (never a plan field), and runs
    it read-only. A plan outside the capability set -> 422 (`ValidationFailed`)."""
    return await runner.run(plan, principal.tenant_id)
