"""Internal attack-chain read API (service-JWT, audience `correlation-engine`).

The tenant scope is always the token's `tenant_id`, never a query field.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from sm_common.errors import NotFound
from sm_common.security import InternalPrincipal
from sm_contracts import AttackChainModel, ChainStatus

from ..chains import ChainRepository
from ..deps import get_principal, get_repo
from ..schemas import ChainListResponse
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/chains", tags=["chains"])


@router.get("", response_model=ChainListResponse)
async def list_chains(
    status: ChainStatus | None = Query(default=None),
    min_score: float | None = Query(default=None, ge=0.0, le=1.0),
    limit: int = Query(default=100, ge=1, le=500),
    principal: InternalPrincipal = Depends(get_principal),
    repo: ChainRepository = Depends(get_repo),
) -> ChainListResponse:
    rows = await repo.list_chains(
        principal.tenant_id, status=status, min_score=min_score, limit=limit
    )
    return ChainListResponse(count=len(rows), chains=rows)


@router.get("/{chain_id}", response_model=AttackChainModel)
async def get_chain(
    chain_id: UUID,
    principal: InternalPrincipal = Depends(get_principal),
    repo: ChainRepository = Depends(get_repo),
) -> AttackChainModel:
    chain = await repo.get_chain(principal.tenant_id, chain_id)
    if chain is None:
        raise NotFound("attack chain not found")
    return chain
