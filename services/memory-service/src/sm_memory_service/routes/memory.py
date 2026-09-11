"""Threat-memory retrieval API. Internal-JWT only.

`POST /api/v1/memory/similar` is the one similarity endpoint — it never
returns a raw feature vector, only `SimilarityMatch.score` and whether the
match came from the pgvector index or the exact-match fallback.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from sm_common.errors import NotFound
from sm_common.security import InternalPrincipal
from sm_contracts import AdversaryFingerprint, Campaign, SimilarityMatch, SmBaseModel, ThreatMemory

from ..deps import Services, get_principal, get_repository, get_services
from ..repository import MemoryRepository
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/memory", tags=["memory"])


class SimilarityRequest(SmBaseModel):
    kind: Literal["threat_memory", "campaign", "adversary_fingerprint"]
    technique_ids: list[str] = Field(min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=50)


@router.post("/similar", response_model=list[SimilarityMatch])
async def find_similar(
    body: SimilarityRequest,
    principal: InternalPrincipal = Depends(get_principal),
    repo: MemoryRepository = Depends(get_repository),
    services: Services = Depends(get_services),
) -> list[SimilarityMatch]:
    matches = await repo.find_similar(
        principal.tenant_id, kind=body.kind, technique_ids=body.technique_ids, limit=body.limit
    )
    if matches and matches[0].exact_fallback:
        services.mem_metrics.similarity_fell_back()
    return matches


@router.get("/patterns", response_model=list[ThreatMemory])
async def list_patterns(
    subject_type: str | None = Query(default=None),
    subject_id: str | None = Query(default=None),
    principal: InternalPrincipal = Depends(get_principal),
    repo: MemoryRepository = Depends(get_repository),
) -> list[ThreatMemory]:
    return await repo.list_patterns(principal.tenant_id, subject_type=subject_type, subject_id=subject_id)


@router.get("/fingerprints/{subject_type}/{subject_id}", response_model=AdversaryFingerprint)
async def get_fingerprint(
    subject_type: str,
    subject_id: str,
    principal: InternalPrincipal = Depends(get_principal),
    repo: MemoryRepository = Depends(get_repository),
) -> AdversaryFingerprint:
    found = await repo.get_fingerprint(
        principal.tenant_id, subject_type=subject_type, subject_id=subject_id
    )
    if found is None:
        raise NotFound("no fingerprint for that subject")
    return found


@router.get("/campaigns", response_model=list[Campaign])
async def list_campaigns(
    status: str | None = Query(default=None),
    principal: InternalPrincipal = Depends(get_principal),
    repo: MemoryRepository = Depends(get_repository),
) -> list[Campaign]:
    return await repo.list_campaigns(principal.tenant_id, status=status)


@router.get("/campaigns/{campaign_id}", response_model=Campaign)
async def get_campaign(
    campaign_id: UUID,
    principal: InternalPrincipal = Depends(get_principal),
    repo: MemoryRepository = Depends(get_repository),
) -> Campaign:
    found = await repo.get_campaign(principal.tenant_id, campaign_id)
    if found is None:
        raise NotFound("campaign not found")
    return found
