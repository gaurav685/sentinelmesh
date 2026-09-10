"""Multi-agent defense contracts (Phase 10, Unit 4).

`api-gateway` gathers the evidence and asks `ai-analyst` to run a named defense
agent over it. An agent produces **findings** and, for the response agent,
**proposed actions** — which are never executed. `decision` on a proposed action
is the `action_gate` verdict; in this build it is never `allowed`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from ..common import SmBaseModel, to_utc
from .analyst import EvidenceRef

__all__ = [
    "AgentFinding",
    "AgentName",
    "AgentRunRequest",
    "AgentRunResult",
    "ProposedActionOut",
]

AgentName = Literal["detection-agent", "threat-intel-agent", "response-orchestration-agent"]
AgentRunStatus = Literal[
    "completed", "cancelled", "timeout", "step_limit", "tool_limit", "budget_exhausted", "failed"
]


class AgentRunRequest(SmBaseModel):
    agent: AgentName
    subject_type: Literal["detection", "attack_chain", "incident"]
    subject_id: str = Field(min_length=1, max_length=128)
    task: str = Field(min_length=1, max_length=2_000)
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=100)


class AgentFinding(SmBaseModel):
    kind: str = Field(min_length=1, max_length=48)
    summary: str = Field(min_length=1, max_length=2_000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)
    confidence: Literal["low", "medium", "high"] = "low"


class ProposedActionOut(SmBaseModel):
    action_type: str = Field(min_length=1, max_length=64)
    target: str = Field(min_length=1, max_length=200)
    rationale: str = Field(default="", max_length=2_000)
    reversible: bool = True
    #: The `action_gate` verdict. Never `allowed` in this build.
    decision: Literal["denied", "approval_required", "allowed"] = "approval_required"


class AgentRunResult(SmBaseModel):
    agent: AgentName
    status: AgentRunStatus
    steps_used: int = Field(ge=0)
    tool_calls_used: int = Field(ge=0)
    tokens_spent: int = Field(ge=0)
    findings: list[AgentFinding] = Field(default_factory=list, max_length=100)
    proposed_actions: list[ProposedActionOut] = Field(default_factory=list, max_length=50)
    detail: str = Field(default="", max_length=300)
    generated_at: datetime

    @field_validator("generated_at")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return to_utc(v)
