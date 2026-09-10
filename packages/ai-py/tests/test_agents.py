from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel, Field

from sm_ai.adapters import DeterministicAdapter
from sm_ai.agents import (
    DETECTION_AGENT,
    RESPONSE_AGENT,
    AgentLimits,
    ProposedAction,
    action_gate,
    run_agent,
)
from sm_ai.client import LlmClient
from sm_ai.evidence import EvidenceBuilder
from sm_ai.messages import FinishReason, LlmRequest, LlmResponse, ToolCall
from sm_ai.registry import ToolRegistry
from sm_ai.tools import FunctionTool, ToolContext, ToolOutcome

from .conftest import FakePrincipal


def _bundle() -> object:
    return (
        EvidenceBuilder()
        .add("detection", "det-1", "detection-engine:x", "12 failed logins for svc-backup")
        .add("technique", "T1110", "mitre:catalog", "Brute Force", trusted=True)
        .build()
    )


class _Q(BaseModel):
    query: str = Field(min_length=1)


def _registry(calls: list[str] | None = None) -> ToolRegistry:
    async def _search(args: _Q, _ctx: ToolContext) -> ToolOutcome:
        if calls is not None:
            calls.append(args.query)
        return ToolOutcome(ok=True, content="[det-1] detection: 12 failed logins")

    reg = ToolRegistry()
    reg.register(
        FunctionTool(
            name="search_evidence",
            description="search",
            args_model=_Q,
            handler=_search,
            required_permission=None,
        )
    )
    return reg


def _client(provider: DeterministicAdapter) -> LlmClient:
    return LlmClient(provider=provider, max_prompt_tokens=100_000, timeout_s=2.0, max_retries=0)


async def test_agent_uses_a_tool_then_reports_findings() -> None:
    searches: list[str] = []
    step = {"n": 0}

    def handler(_req: LlmRequest) -> LlmResponse:
        step["n"] += 1
        if step["n"] == 1:
            return LlmResponse(
                text="",
                tool_calls=(ToolCall(id="c1", name="search_evidence", arguments={"query": "login"}),),
                finish_reason=FinishReason.tool_call,
            )
        return LlmResponse(text="- Repeated failed logins indicate brute force [det-1]")

    report = await run_agent(
        DETECTION_AGENT,
        "Assess this detection.",
        _bundle(),  # type: ignore[arg-type]
        llm=_client(DeterministicAdapter(handler)),
        registry=_registry(searches),
        principal=FakePrincipal(),
        model="m",
        correlation_id="corr",
    )
    assert report.status == "completed"
    assert report.tool_calls_used == 1 and searches == ["login"]
    assert report.findings and report.findings[0].evidence_refs == ("det-1",)


async def test_a_tool_the_agent_is_not_allowed_is_refused_mid_run() -> None:
    step = {"n": 0}

    def handler(_req: LlmRequest) -> LlmResponse:
        step["n"] += 1
        if step["n"] == 1:
            # ask for a tool the detection agent's spec does not allow
            return LlmResponse(
                text="",
                tool_calls=(ToolCall(id="c1", name="disable_user", arguments={}),),
            )
        return LlmResponse(text="- Could not disable anything [det-1]")

    report = await run_agent(
        DETECTION_AGENT,
        "t",
        _bundle(),  # type: ignore[arg-type]
        llm=_client(DeterministicAdapter(handler)),
        registry=_registry(),
        principal=FakePrincipal(),
        model="m",
        correlation_id="c",
    )
    assert report.status == "completed"  # the run continued
    assert report.tool_calls_used == 1


async def test_the_step_limit_stops_a_tool_looping_agent() -> None:
    def handler(_req: LlmRequest) -> LlmResponse:
        return LlmResponse(
            text="",
            tool_calls=(ToolCall(id="c", name="search_evidence", arguments={"query": "x"}),),
        )

    report = await run_agent(
        DETECTION_AGENT,
        "t",
        _bundle(),  # type: ignore[arg-type]
        llm=_client(DeterministicAdapter(handler)),
        registry=_registry(),
        principal=FakePrincipal(),
        model="m",
        correlation_id="c",
        limits=AgentLimits(max_steps=3, max_tool_calls=100),
    )
    assert report.status == "step_limit"
    assert report.steps_used == 3


async def test_the_tool_call_limit_stops_the_run() -> None:
    def handler(_req: LlmRequest) -> LlmResponse:
        return LlmResponse(
            text="",
            tool_calls=tuple(
                ToolCall(id=f"c{i}", name="search_evidence", arguments={"query": "x"})
                for i in range(5)
            ),
        )

    report = await run_agent(
        DETECTION_AGENT,
        "t",
        _bundle(),  # type: ignore[arg-type]
        llm=_client(DeterministicAdapter(handler)),
        registry=_registry(),
        principal=FakePrincipal(),
        model="m",
        correlation_id="c",
        limits=AgentLimits(max_steps=10, max_tool_calls=3),
    )
    assert report.status == "tool_limit"
    assert report.tool_calls_used == 3


async def test_cancellation_stops_the_agent() -> None:
    cancel = asyncio.Event()
    cancel.set()
    report = await run_agent(
        DETECTION_AGENT,
        "t",
        _bundle(),  # type: ignore[arg-type]
        llm=_client(DeterministicAdapter.canned("- x [det-1]")),
        registry=_registry(),
        principal=FakePrincipal(),
        model="m",
        correlation_id="c",
        cancel=cancel,
    )
    assert report.status == "cancelled"


async def test_the_response_agent_proposes_but_the_gate_denies() -> None:
    report = await run_agent(
        RESPONSE_AGENT,
        "Recommend containment.",
        _bundle(),  # type: ignore[arg-type]
        llm=_client(
            DeterministicAdapter.canned(
                "- Isolate the host [det-1]\nPROPOSE: isolate_host svc-backup :: brute force in progress"
            )
        ),
        registry=_registry(),
        principal=FakePrincipal(),
        model="m",
        correlation_id="c",
    )
    assert report.status == "completed"
    assert len(report.proposed_actions) == 1
    a = report.proposed_actions[0]
    assert a.action_type == "isolate_host" and a.target == "svc-backup"
    # suggest_only -> denied; nothing is executed here regardless
    assert action_gate(
        a, response_mode="suggest_only", approval_required=True, is_production=False,
        policy_signed=False,
    ) == "denied"


@pytest.mark.parametrize(
    ("mode", "approval", "prod", "signed", "expected"),
    [
        ("suggest_only", True, True, True, "denied"),
        ("approve_required", True, True, True, "approval_required"),
        ("auto", True, True, True, "approval_required"),  # approval still required
        ("auto", False, False, True, "approval_required"),  # not production
        ("auto", False, True, False, "approval_required"),  # no signed policy
        ("auto", False, True, True, "allowed"),  # only here
    ],
)
def test_action_gate_truth_table(
    mode: str, approval: bool, prod: bool, signed: bool, expected: str
) -> None:
    a = ProposedAction(action_type="block_ip", target="10.0.0.9", rationale="c2", reversible=True)
    assert action_gate(
        a, response_mode=mode, approval_required=approval, is_production=prod, policy_signed=signed
    ) == expected


def test_action_gate_never_allows_an_irreversible_action_without_review() -> None:
    a = ProposedAction(action_type="wipe_host", target="h", rationale="x", reversible=False)
    assert action_gate(
        a, response_mode="auto", approval_required=False, is_production=True, policy_signed=True
    ) == "approval_required"
