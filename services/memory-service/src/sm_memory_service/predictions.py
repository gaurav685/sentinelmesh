"""Wires `sm_ml.predict`'s deterministic heuristics to real data: the full
chain (via `ChainsClient`), threat-memory patterns, adversary fingerprints,
and campaigns (via `MemoryRepository`). No trained model — see
`sm_ml.predict`'s docstring. Every result is a `Prediction` carrying its own
confidence, evidence, model version, and generation time.
"""

from __future__ import annotations

from uuid import UUID

from sm_common.clock import utcnow
from sm_common.errors import NotFound
from sm_contracts import (
    AttackStage,
    Prediction,
    PredictionKind,
    ThreatSubjectType,
)
from sm_ml.predict import (
    MODEL_VERSION,
    PredictionOutcome,
    predict_attack_progression,
    predict_lateral_movement,
    predict_next_action,
    predict_threat_trajectory,
)

from .chains_client import ChainsClient
from .repository import MemoryRepository

__all__ = ["PredictionService"]


def _to_contract(
    kind: PredictionKind, subject_type: ThreatSubjectType | None, subject_id: str,
    outcome: PredictionOutcome,
) -> Prediction:
    return Prediction(
        kind=kind, subject_type=subject_type, subject_id=subject_id,
        prediction=outcome.prediction, confidence=outcome.confidence,
        evidence=list(outcome.evidence), features=dict(outcome.features),
        model_version=MODEL_VERSION, generated_at=utcnow(),
    )


class PredictionService:
    def __init__(self, *, repo: MemoryRepository, chains: ChainsClient) -> None:
        self._repo = repo
        self._chains = chains

    async def attack_progression(self, tenant_id: UUID, chain_id: UUID) -> Prediction:
        chain = await self._chains.get_chain(tenant_id, chain_id)
        if chain is None:
            raise NotFound("chain not found")
        latest_stage = (
            max(chain.stages, key=lambda s: s.stage_order).stage
            if chain.stages else AttackStage.unknown
        )
        outcome = predict_attack_progression(
            latest_stage=latest_stage, distinct_stage_count=chain.distinct_stage_count,
            chain_score=chain.score, chain_confidence=chain.confidence,
        )
        return _to_contract("attack_progression", chain.subject_type, chain.subject_id, outcome)

    async def next_action(self, tenant_id: UUID, chain_id: UUID) -> Prediction:
        chain = await self._chains.get_chain(tenant_id, chain_id)
        if chain is None:
            raise NotFound("chain not found")
        patterns = await self._repo.list_patterns(
            tenant_id, subject_type=chain.subject_type.value, subject_id=chain.subject_id,
        )
        pattern_technique_ids = sorted({t for p in patterns for t in p.technique_ids})
        outcome = predict_next_action(
            pattern_technique_ids=pattern_technique_ids, chain_technique_ids=chain.technique_ids,
        )
        return _to_contract("next_action", chain.subject_type, chain.subject_id, outcome)

    async def lateral_movement(
        self, tenant_id: UUID, *, subject_type: ThreatSubjectType, subject_id: str,
    ) -> Prediction:
        fingerprint = await self._repo.get_fingerprint(
            tenant_id, subject_type=subject_type.value, subject_id=subject_id,
        )
        if fingerprint is None:
            raise NotFound("no fingerprint for that subject")
        others = await self._repo.list_fingerprints(
            tenant_id, exclude_subject_type=subject_type.value, exclude_subject_id=subject_id,
        )
        candidates = [(o.subject_type.value, o.subject_id, o.technique_ids) for o in others]
        outcome = predict_lateral_movement(
            subject_technique_ids=fingerprint.technique_ids, candidates=candidates,
        )
        return _to_contract("lateral_movement", subject_type, subject_id, outcome)

    async def threat_trajectory(self, tenant_id: UUID, campaign_id: UUID) -> Prediction:
        campaign = await self._repo.get_campaign(tenant_id, campaign_id)
        if campaign is None:
            raise NotFound("campaign not found")
        outcome = predict_threat_trajectory(
            status=campaign.status, chain_count=len(campaign.chain_ids),
        )
        return _to_contract("threat_trajectory", None, str(campaign_id), outcome)
