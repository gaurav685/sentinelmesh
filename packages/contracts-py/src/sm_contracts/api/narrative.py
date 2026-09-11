"""Attack storytelling contracts (Phase 14; req 33).

`services/ai-analyst` narrates one attack chain as an ordered sequence of
`NarrativeBeat`s. Every beat's factual fields (`stage`, `detection_ids`,
`technique_ids`, timestamps) come straight from `correlation-engine`'s own
`ChainStageModel` — never touched by the LLM, never fabricated. `tier` is
`synthetic` for a chain whose subject is a simulation-generated id
(`sm_ml.scenario.is_synthetic_id`) and `evidence` otherwise; a narrative
never claims a simulated chain is real.

`summary` is the one LLM-composed part — a grounded walkthrough that must
cite a beat's `stage` value in every sentence, using the exact grounded-
citation-and-retry mechanism `IncidentAnalyst.explain` already uses. When no
live LLM is configured, or the model's output fails grounding, `summary` is
a deterministic factual template instead and `degraded=True` — the contract
never distinguishes "real narrative" from "template" by omission.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from ..chains import AttackStage
from ..common import SmBaseModel, TenantScoped, TimestampedModel, to_utc
from ..enums import ThreatSubjectType
from ..report import GroundingKind
from .analyst import AnalystModelInfo

__all__ = ["Narrative", "NarrativeBeat"]


class NarrativeBeat(SmBaseModel):
    """One kill-chain stage, narrated. Deterministic — mirrors
    `ChainStageModel` exactly, never touched by the LLM."""

    at: datetime
    stage: AttackStage
    title: str = Field(min_length=1, max_length=120)
    detection_ids: list[str] = Field(default_factory=list, max_length=2000)
    technique_ids: list[str] = Field(default_factory=list, max_length=64)
    detection_count: int = Field(ge=0)
    tier: GroundingKind

    @field_validator("at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)


class Narrative(TenantScoped, TimestampedModel):
    """A cinematic breach replay for one attack chain."""

    id: UUID
    chain_id: UUID
    subject_type: ThreatSubjectType
    subject_id: str = Field(min_length=1, max_length=256)
    beats: list[NarrativeBeat] = Field(default_factory=list, max_length=15)
    #: Grounded prose citing each beat's `stage` value in `[stage_name]`
    #: form — or a deterministic factual template when `degraded`.
    summary: str = Field(min_length=1, max_length=8_000)
    cited_refs: list[str] = Field(default_factory=list, max_length=15)
    confidence: Literal["low", "medium", "high"] = "low"
    model: AnalystModelInfo = Field(default_factory=AnalystModelInfo)
    #: `True` when `summary` is the deterministic template (no live LLM, or
    #: the model's output failed grounding validation) — never a live
    #: narrative silently downgraded without saying so.
    degraded: bool = False
    degraded_reason: str = Field(default="", max_length=200)
    #: `True` when every beat's evidence traces back to a
    #: simulation-generated subject id — the whole narrative is then
    #: `GroundingKind.synthetic`, never presented as a real incident.
    simulated: bool = False
    generated_at: datetime

    @field_validator("generated_at")
    @classmethod
    def _utc_generated(cls, v: datetime) -> datetime:
        return to_utc(v)
