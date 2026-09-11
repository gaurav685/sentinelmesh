"""`GET /api/v1/incidents/{chain_id}/narrative` — attack storytelling (req 33).

Internal-JWT only. "Incident" here is an attack chain — this platform has
no separate `Incident` entity (`docs/CONTRACTS.md` §3 still lists one as
PLANNED) — so the id in the path is `correlation-engine`'s own chain id.
Narrates the chain's real, current stages; never invents one.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from sm_common.clock import utcnow
from sm_common.errors import NotFound
from sm_common.security import InternalPrincipal
from sm_contracts import Narrative

from ..chains_client import ChainsClient
from ..deps import Services, get_narrative_composer, get_narrative_repository, get_principal, get_services
from ..narrative import NarrativeComposer
from ..repository import NarrativeRepository
from ..version import API_PREFIX

__all__ = ["router"]

router = APIRouter(prefix=f"{API_PREFIX}/incidents", tags=["narrative"])


@router.get("/{chain_id}/narrative", response_model=Narrative)
async def get_narrative(
    chain_id: UUID,
    principal: InternalPrincipal = Depends(get_principal),
    services: Services = Depends(get_services),
    composer: NarrativeComposer = Depends(get_narrative_composer),
    repo: NarrativeRepository = Depends(get_narrative_repository),
) -> Narrative:
    chains: ChainsClient = services.chains
    chain = await chains.get_chain(principal.tenant_id, chain_id)
    if chain is None:
        raise NotFound("attack chain not found")

    body = await composer.compose(chain)
    return await repo.upsert(
        principal.tenant_id, chain_id, subject_type=chain.subject_type.value,
        subject_id=chain.subject_id, body=body, generated_at=utcnow(),
    )
