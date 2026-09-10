"""AI analyst contracts (Phase 10).

`api-gateway` gathers the evidence for a subject (a detection / chain / incident)
and asks `ai-analyst` to explain it. The analyst answers **only** from that
evidence; every sentence of `summary` cites an evidence `ref` in [brackets]. When
no live LLM is reachable the analyst returns a deterministic, factual template
with `degraded = true` — it never fabricates a narrative.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from ..common import SmBaseModel, to_utc

__all__ = [
    "AnalystModelInfo",
    "AnalystTask",
    "EvidenceRef",
    "ExplainRequest",
    "Explanation",
]

AnalystTask = Literal["summarize", "triage", "reason", "remediate"]
AnalystSubject = Literal["detection", "attack_chain", "incident"]


class EvidenceRef(SmBaseModel):
    """One piece of platform-gathered evidence. `trusted` is `True` only for
    strings SentinelMesh itself produced (a rule id, a numeric score, a catalog
    technique id); everything telemetry- or third-party-derived is `False` and is
    fenced as data before it reaches the model."""

    kind: str = Field(min_length=1, max_length=48)
    ref: str = Field(min_length=1, max_length=96)
    provenance: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=20_000)
    trusted: bool = False


class ExplainRequest(SmBaseModel):
    subject_type: AnalystSubject
    subject_id: str = Field(min_length=1, max_length=128)
    task: AnalystTask = "summarize"
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=100)


class AnalystModelInfo(SmBaseModel):
    provider: str = Field(default="", max_length=32)
    model_id: str = Field(default="", max_length=128)
    #: sha256 of the exact prompt sent — for audit correlation, not the prompt.
    prompt_sha256: str = Field(default="", max_length=64)
    #: `True` only when a remote provider actually answered.
    from_live_provider: bool = False


class Explanation(SmBaseModel):
    subject_type: AnalystSubject
    subject_id: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=8_000)
    #: The evidence refs cited by `summary`. Every one is present in the request.
    cited_refs: list[str] = Field(default_factory=list, max_length=100)
    confidence: Literal["low", "medium", "high"] = "low"
    recommendations: list[str] = Field(default_factory=list, max_length=20)
    model: AnalystModelInfo = Field(default_factory=AnalystModelInfo)
    generated_at: datetime
    #: `True` when the answer is the deterministic template (no live LLM, or the
    #: model's output failed grounding validation).
    degraded: bool = False
    degraded_reason: str = Field(default="", max_length=200)
    #: `True` when the gathered evidence contained a prompt-injection pattern
    #: (still answered — the content was fenced — but flagged for the analyst).
    evidence_flagged: bool = False

    @field_validator("generated_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)
