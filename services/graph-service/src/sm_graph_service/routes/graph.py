"""Internal graph-query API (Phase 4 Unit 3).

Read-only. Every query is scoped to `principal.tenant_id` (from the verified
internal JWT), parameterized, depth-bounded and row-capped by the repository.
No endpoint accepts raw Cypher.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from sm_common.errors import NotFound
from sm_common.security import InternalPrincipal

from ..deps import get_principal, get_repository
from ..repository import GraphRepository
from ..schemas import EntityResponse, GraphNodeModel, NeighborsResponse, PathResponse
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
