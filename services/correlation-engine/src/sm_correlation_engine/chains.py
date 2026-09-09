"""The attack-chain store and the correlation step.

One `StagedDetection` -> one `attack_chain_stage` row (its detections held as a
set, so an at-least-once redelivery is a no-op) -> a recomputed `attack_chain`
row (progression / confidence / status / score). Timestamps are widened by `min`
/ `max`, so an out-of-order detection reshapes the chain correctly. `ti_corroborated`
is monotonic once any member detection is threat-intel-backed.

The chain id is deterministic (`chain_id_for(chain_dedup_key, chain_window_start)`),
so the same detection always lands in the same chain.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sm_common.clock import utcnow
from sm_common.db import AttackChainRow, AttackChainStageRow, Database, ThreatScore
from sm_common.ids import uuid7
from sm_contracts import (
    STAGE_ORDER,
    AttackChainModel,
    AttackChainPayload,
    AttackStage,
    ChainStageModel,
    ChainStatus,
    ScoringStatus,
    Severity,
    ThreatSubjectType,
    chain_dedup_key,
    chain_id_for,
    chain_window_start,
)

from .scoring import ChainScore, chain_confidence, chain_progression, score_chain
from .staging import StagedDetection

__all__ = ["ChainRepository", "ChainUpdate"]

_SEVERITY_ORDER = list(Severity)


def _worse(a: Severity, b: Severity) -> Severity:
    return a if _SEVERITY_ORDER.index(a) >= _SEVERITY_ORDER.index(b) else b


def _as_uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


@dataclass(frozen=True)
class ChainUpdate:
    chain: AttackChainModel
    payload: AttackChainPayload
    created: bool
    new_detection: bool


class ChainRepository:
    def __init__(self, db: Database, *, window_seconds: int, dormant_seconds: int) -> None:
        self._db = db
        self._window = window_seconds
        self._dormant = dormant_seconds

    async def correlate(
        self,
        staged: StagedDetection,
        *,
        tenant_id: str | uuid.UUID,
        subject_type: ThreatSubjectType,
        subject_id: str,
        now: datetime | None = None,
    ) -> ChainUpdate:
        now = now or utcnow()
        tid = _as_uuid(tenant_id)
        dedup = chain_dedup_key(tid, subject_type, subject_id)
        window_start = chain_window_start(staged.occurred_at, self._window)
        chain_id = chain_id_for(dedup, window_start)
        occurred = staged.occurred_at

        async with self._db.transaction() as s:
            chain_row = await s.get(AttackChainRow, chain_id, with_for_update=True)
            created = chain_row is None
            ti_corroborated = staged.ti_corroborated or (
                bool(chain_row.ti_corroborated) if chain_row else False
            )

            if chain_row is None:
                # Insert the chain shell first so the stage row's FK is satisfied.
                # Its aggregate fields are placeholders — overwritten below once the
                # stage exists and can be re-aggregated.
                chain_row = AttackChainRow(
                    id=chain_id, tenant_id=tid, subject_type=subject_type.value,
                    subject_id=subject_id, status=ChainStatus.forming.value,
                    window_start=window_start, first_seen=occurred, last_seen=occurred,
                    distinct_stage_count=0, progression=0.0, confidence=0.0, score=0.0,
                    score_version="v1", scoring_status=ScoringStatus.degraded.value,
                    ti_corroborated=ti_corroborated, technique_ids=[], detection_count=0, notes=[],
                )
                s.add(chain_row)
                await s.flush()

            stage_row = (
                await s.execute(
                    select(AttackChainStageRow).where(
                        AttackChainStageRow.chain_id == chain_id,
                        AttackChainStageRow.stage == staged.stage.value,
                    ).with_for_update()
                )
            ).scalar_one_or_none()

            det_ids = list(stage_row.detection_ids) if stage_row else []
            new_detection = staged.detection_id not in det_ids
            if new_detection:
                det_ids.append(staged.detection_id)

            techniques = sorted(
                set(stage_row.technique_ids if stage_row else []) | set(staged.technique_ids)
            )
            first_seen = min(stage_row.first_seen, occurred) if stage_row else occurred
            last_seen = max(stage_row.last_seen, occurred) if stage_row else occurred
            max_sev = (
                _worse(Severity(stage_row.max_severity), staged.severity)
                if stage_row else staged.severity
            )
            max_score = (
                max(float(stage_row.max_detection_score), staged.detection_score)
                if stage_row else staged.detection_score
            )

            if stage_row is None:
                s.add(AttackChainStageRow(
                    id=uuid7(), chain_id=chain_id, tenant_id=tid, stage=staged.stage.value,
                    stage_order=staged.stage_order, detection_ids=det_ids, technique_ids=techniques,
                    max_severity=max_sev.value, max_detection_score=max_score,
                    detection_count=len(det_ids), first_seen=first_seen, last_seen=last_seen,
                ))
            else:
                stage_row.detection_ids = det_ids
                stage_row.technique_ids = techniques
                stage_row.max_severity = max_sev.value
                stage_row.max_detection_score = max_score
                stage_row.detection_count = len(det_ids)
                stage_row.first_seen = first_seen
                stage_row.last_seen = last_seen
            await s.flush()

            stages = list((await s.execute(
                select(AttackChainStageRow)
                .where(AttackChainStageRow.chain_id == chain_id)
                .order_by(AttackChainStageRow.first_seen)
            )).scalars())

            agg = _aggregate(
                stages, dormant_seconds=self._dormant, now=now, ti_corroborated=ti_corroborated,
                any_degraded=staged.scoring_status is ScoringStatus.degraded,
            )

            for k, v in _row_fields(agg, ti_corroborated).items():
                setattr(chain_row, k, v)
            await s.flush()
            await s.refresh(chain_row)

            # correlation-engine is the sole writer of `threat_score` (Phase 7):
            # an entity's score is its most-recently-updated chain's score. A
            # max-across-active-chains / time-decay model is deferred.
            await self._upsert_threat_score(
                s, tenant_id=tid, subject_type=subject_type, subject_id=subject_id,
                score=agg.score, now=now,
            )

            model = _to_model(chain_row, stages)

        payload = AttackChainPayload(
            chain_id=model.id, tenant_id=model.tenant_id, subject_type=model.subject_type,
            subject_id=model.subject_id, status=model.status, first_seen=model.first_seen,
            last_seen=model.last_seen, updated_at=model.updated_at, stage_count=len(model.stages),
            distinct_stage_count=model.distinct_stage_count, latest_stage=_latest_stage(stages),
            progression=model.progression, confidence=model.confidence, score=model.score,
            score_version=model.score_version, scoring_status=model.scoring_status,
            ti_corroborated=model.ti_corroborated, technique_ids=model.technique_ids,
            detection_count=model.detection_count,
        )
        return ChainUpdate(chain=model, payload=payload, created=created, new_detection=new_detection)

    @staticmethod
    async def _upsert_threat_score(
        s: AsyncSession, *, tenant_id: uuid.UUID, subject_type: ThreatSubjectType, subject_id: str,
        score: ChainScore, now: datetime,
    ) -> None:
        stmt = insert(ThreatScore).values(
            id=uuid7(), tenant_id=tenant_id, subject_type=subject_type.value, subject_id=subject_id,
            score=score.score, components=score.components, weights_version=score.version,
            scoring_status=score.scoring_status.value, computed_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_threat_score_subject",
            set_={
                "score": stmt.excluded.score, "components": stmt.excluded.components,
                "weights_version": stmt.excluded.weights_version,
                "scoring_status": stmt.excluded.scoring_status,
                "computed_at": stmt.excluded.computed_at,
            },
        )
        await s.execute(stmt)

    # ---- reads ----------------------------------------------------
    async def get_chain(self, tenant_id: str | uuid.UUID, chain_id: str | uuid.UUID) -> AttackChainModel | None:
        async with self._db.session() as s:
            row = await s.get(AttackChainRow, _as_uuid(chain_id))
            if row is None or row.tenant_id != _as_uuid(tenant_id):
                return None
            stages = list((await s.execute(
                select(AttackChainStageRow).where(AttackChainStageRow.chain_id == row.id)
            )).scalars())
        return _to_model(row, stages)

    async def list_chains(
        self, tenant_id: str | uuid.UUID, *, status: ChainStatus | None = None,
        min_score: float | None = None, limit: int = 100,
    ) -> list[AttackChainModel]:
        stmt = (
            select(AttackChainRow)
            .where(AttackChainRow.tenant_id == _as_uuid(tenant_id))
            .order_by(AttackChainRow.last_seen.desc())
            .limit(limit)
        )
        if status is not None:
            stmt = stmt.where(AttackChainRow.status == status.value)
        if min_score is not None:
            stmt = stmt.where(AttackChainRow.score >= min_score)
        async with self._db.session() as s:
            rows = list((await s.execute(stmt)).scalars())
        return [_to_model(r, []) for r in rows]  # list view omits per-stage detail


# --------------------------------------------------------------------------- #
# aggregation (pure)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _Aggregate:
    status: ChainStatus
    first_seen: datetime
    last_seen: datetime
    distinct_real_stages: int
    progression: float
    confidence: float
    score: ChainScore
    technique_ids: list[str]
    detection_count: int
    notes: list[str]


def _row_fields(agg: _Aggregate, ti_corroborated: bool) -> dict[str, object]:
    return {
        "status": agg.status.value,
        "first_seen": agg.first_seen,
        "last_seen": agg.last_seen,
        "distinct_stage_count": agg.distinct_real_stages,
        "progression": agg.progression,
        "confidence": agg.confidence,
        "score": agg.score.score,
        "score_version": agg.score.version,
        "scoring_status": agg.score.scoring_status.value,
        "ti_corroborated": ti_corroborated,
        "technique_ids": agg.technique_ids,
        "detection_count": agg.detection_count,
        "notes": agg.notes,
    }


def _aggregate(
    stages: list[AttackChainStageRow], *, dormant_seconds: int, now: datetime,
    ti_corroborated: bool, any_degraded: bool,
) -> _Aggregate:
    first_seen = min(st.first_seen for st in stages)
    last_seen = max(st.last_seen for st in stages)
    techniques = sorted({t for st in stages for t in st.technique_ids})
    detection_count = sum(int(st.detection_count) for st in stages)
    real = [st for st in stages if int(st.stage_order) >= 0]
    distinct_real = len(real)
    progression = chain_progression([int(st.stage_order) for st in stages])

    ordered_real = sorted(real, key=lambda st: st.first_seen)
    total_transitions = max(0, len(ordered_real) - 1)
    out_of_order = sum(
        1 for prev, nxt in pairwise(ordered_real)
        if int(nxt.stage_order) < int(prev.stage_order)
    )

    max_sev = Severity.info
    for st in stages:
        cand = Severity(st.max_severity)
        if _SEVERITY_ORDER.index(cand) > _SEVERITY_ORDER.index(max_sev):
            max_sev = cand
    max_score = max((float(st.max_detection_score) for st in stages), default=0.0)

    strong = max_sev in (Severity.high, Severity.critical) or ti_corroborated
    confidence = chain_confidence(
        distinct_real_stages=distinct_real, detection_count=detection_count,
        out_of_order_transitions=out_of_order, total_transitions=total_transitions,
        has_strong_signal=strong,
    )

    unknown_detections = sum(
        int(st.detection_count) for st in stages if st.stage == AttackStage.unknown.value
    )
    mostly_unmapped = detection_count > 0 and unknown_detections * 2 > detection_count
    score = score_chain(
        max_severity=max_sev, max_detection_score=max_score, ti_corroborated=ti_corroborated,
        progression=progression, confidence=confidence,
        degraded_evidence=any_degraded or mostly_unmapped,
    )

    idle = (now - last_seen).total_seconds()
    if idle >= dormant_seconds:
        status = ChainStatus.dormant
    elif distinct_real <= 1:
        status = ChainStatus.forming
    else:
        status = ChainStatus.active

    notes: list[str] = []
    if out_of_order:
        notes.append("out_of_order_observed")
    if mostly_unmapped:
        notes.append("mostly_unmapped_techniques")
    if {Severity.critical.value, Severity.low.value} <= {st.max_severity for st in stages}:
        notes.append("conflicting_severity")

    return _Aggregate(
        status=status, first_seen=first_seen, last_seen=last_seen,
        distinct_real_stages=distinct_real, progression=progression, confidence=confidence,
        score=score, technique_ids=techniques, detection_count=detection_count, notes=notes,
    )


def _latest_stage(stages: list[AttackChainStageRow]) -> AttackStage:
    if not stages:
        return AttackStage.unknown
    return AttackStage(max(stages, key=lambda st: st.last_seen).stage)


def _to_model(row: AttackChainRow, stages: list[AttackChainStageRow]) -> AttackChainModel:
    return AttackChainModel(
        id=row.id, tenant_id=row.tenant_id, created_at=row.created_at, updated_at=row.updated_at,
        subject_type=ThreatSubjectType(row.subject_type), subject_id=row.subject_id,
        status=ChainStatus(row.status), window_start=row.window_start,
        first_seen=row.first_seen, last_seen=row.last_seen,
        stages=[
            ChainStageModel(
                stage=AttackStage(st.stage), stage_order=int(st.stage_order),
                detection_ids=list(st.detection_ids), technique_ids=list(st.technique_ids),
                max_severity=Severity(st.max_severity),
                max_detection_score=float(st.max_detection_score),
                detection_count=int(st.detection_count), first_seen=st.first_seen, last_seen=st.last_seen,
            )
            for st in sorted(stages, key=lambda s: STAGE_ORDER[AttackStage(s.stage)])
        ],
        distinct_stage_count=int(row.distinct_stage_count), progression=float(row.progression),
        confidence=float(row.confidence), score=float(row.score), score_version=row.score_version,
        scoring_status=ScoringStatus(row.scoring_status), ti_corroborated=bool(row.ti_corroborated),
        technique_ids=list(row.technique_ids), detection_count=int(row.detection_count),
        notes=list(row.notes),
    )
