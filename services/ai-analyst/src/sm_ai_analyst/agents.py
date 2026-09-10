"""The multi-agent defense runner (Phase 10, Unit 4).

`api-gateway` gathers the evidence and asks for a named agent to run over it. The
agent works **only** from that evidence — the sole tool, `search_evidence`,
searches the provided bundle and needs no permission. Any other tool the agent's
spec allows is deliberately **not registered here**, so a model that asks for it
gets an `UnknownToolError` back and the run continues. The agent principal holds
**no standing permissions** — an LLM cannot acquire one by asking.

The response agent may emit proposals; `sm_ai.action_gate` decides what happens
to each (in this build: never `allowed`, because `SM_RESPONSE_MODE` is
`suggest_only` and approval is required).
"""

from __future__ import annotations

import uuid
from uuid import UUID

from pydantic import BaseModel, Field

from sm_ai import (
    DETECTION_AGENT,
    RESPONSE_AGENT,
    THREAT_INTEL_AGENT,
    AgentLimits,
    AgentSpec,
    EvidenceBuilder,
    EvidenceBundle,
    FunctionTool,
    LlmClient,
    ToolContext,
    ToolOutcome,
    ToolRegistry,
    action_gate,
    run_agent,
)
from sm_common.clock import utcnow
from sm_common.config import AppSettings
from sm_contracts import AgentFinding, AgentRunRequest, AgentRunResult, PermissionCode, ProposedActionOut

__all__ = ["AgentRunner"]

_SPECS: dict[str, AgentSpec] = {
    DETECTION_AGENT.name: DETECTION_AGENT,
    THREAT_INTEL_AGENT.name: THREAT_INTEL_AGENT,
    RESPONSE_AGENT.name: RESPONSE_AGENT,
}


class _AgentPrincipal:
    """A defense agent's identity. It has NO standing permissions."""

    def __init__(self, tenant_id: UUID, agent_name: str) -> None:
        self._tenant = tenant_id
        self._subject = f"agent:{agent_name}"

    @property
    def tenant_id(self) -> UUID:
        return self._tenant

    @property
    def subject(self) -> str:
        return self._subject

    def has_permission(self, code: PermissionCode) -> bool:
        return False


class _SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200)


def _build_registry(bundle: EvidenceBundle) -> ToolRegistry:
    async def _search(args: _SearchArgs, _ctx: ToolContext) -> ToolOutcome:
        q = args.query.lower()
        hits = [
            f"[{i.ref}] {i.kind}: {' '.join(i.content.split())[:200]}"
            for i in bundle.items
            if q in i.content.lower() or q in i.kind.lower() or q in i.ref.lower()
        ]
        if not hits:
            return ToolOutcome(ok=True, content="no evidence items match that query")
        return ToolOutcome(ok=True, content="\n".join(hits[:10]))

    reg = ToolRegistry()
    reg.register(
        FunctionTool(
            name="search_evidence",
            description="Search the provided evidence bundle for items matching a substring.",
            args_model=_SearchArgs,
            handler=_search,
            required_permission=None,
        )
    )
    return reg


class AgentRunner:
    def __init__(self, llm: LlmClient | None, *, model: str, settings: AppSettings) -> None:
        self._llm = llm
        self._model = model
        self._settings = settings
        self._limits = AgentLimits(
            max_steps=settings.agent_max_steps,
            max_tool_calls=settings.agent_max_tool_calls,
            wall_clock_s=float(settings.agent_wall_clock_timeout_s),
            max_tokens=settings.agent_max_llm_tokens_per_run,
        )

    async def run(self, req: AgentRunRequest, *, tenant_id: UUID | None = None) -> AgentRunResult:
        spec = _SPECS[req.agent]
        builder = EvidenceBuilder()
        for e in req.evidence:
            builder.add(e.kind, e.ref, e.provenance, e.content, trusted=e.trusted)
        bundle = builder.build()

        if self._llm is None:
            return AgentRunResult(
                agent=req.agent,
                status="failed",
                steps_used=0,
                tool_calls_used=0,
                tokens_spent=0,
                detail="llm_unavailable",
                generated_at=utcnow(),
            )

        report = await run_agent(
            spec,
            req.task,
            bundle,
            llm=self._llm,
            registry=_build_registry(bundle),
            principal=_AgentPrincipal(tenant_id or uuid.uuid4(), spec.name),
            model=self._model,
            correlation_id=f"agent-{req.subject_id}",
            limits=self._limits,
        )

        actions: list[ProposedActionOut] = []
        for a in report.proposed_actions:
            decision = action_gate(
                a,
                response_mode=self._settings.response_mode.value,
                approval_required=self._settings.response_approval_required,
                is_production=self._settings.is_production,
                policy_signed=bool(self._settings.response_policy_document_path),
            )
            actions.append(
                ProposedActionOut(
                    action_type=a.action_type,
                    target=a.target,
                    rationale=a.rationale,
                    reversible=a.reversible,
                    decision=decision,
                )
            )

        return AgentRunResult(
            agent=req.agent,
            status=report.status,
            steps_used=report.steps_used,
            tool_calls_used=report.tool_calls_used,
            tokens_spent=report.tokens_spent,
            findings=[
                AgentFinding(
                    kind=f.kind,
                    summary=f.summary,
                    evidence_refs=list(f.evidence_refs),
                    confidence=f.confidence,
                )
                for f in report.findings
            ],
            proposed_actions=actions,
            detail=report.detail,
            generated_at=utcnow(),
        )
