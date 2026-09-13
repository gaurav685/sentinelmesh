"""Autonomous agent safety security tests (Engineering Constitution A§5, ADR-022).

Tests: agent principal holds zero permissions (cannot bypass RBAC), tool allowlist
enforcement (unregistered dangerous tools raise UnknownToolError), action gate
enforces human approval in suggest_only mode, and unknown agent specs are rejected.
"""

from __future__ import annotations

import uuid

import pytest

from sm_ai import (
    EvidenceBuilder,
    ToolCall,
    ToolContext,
    action_gate,
)
from sm_ai.agents import ProposedAction
from sm_ai.errors import UnknownToolError
from sm_ai_analyst.agents import _SPECS, _AgentPrincipal, _build_registry
from sm_contracts import PermissionCode


@pytest.mark.security
def test_agent_principal_has_zero_standing_permissions() -> None:
    """An autonomous agent principal holds NO standing permissions; it cannot
    be granted roles or execute administrative actions."""
    principal = _AgentPrincipal(uuid.uuid4(), "detection-agent")
    # Verify across all known permission codes in the system
    for code in PermissionCode:
        assert principal.has_permission(code) is False, f"Agent should not hold {code}"


@pytest.mark.security
async def test_tool_registry_rejects_unregistered_dangerous_tools() -> None:
    """The agent tool registry only exposes benign evidence search; dangerous tools
    (shell execution, direct DB write, network isolation) are not registered and raise UnknownToolError."""
    builder = EvidenceBuilder()
    builder.add("detection", "det-1", "soc", "Test event content", trusted=True)
    bundle = builder.build()
    reg = _build_registry(bundle)

    # Tool registry should only contain search_evidence
    tool_names = reg.names()
    assert list(tool_names) == ["search_evidence"]

    ctx = ToolContext(principal=_AgentPrincipal(uuid.uuid4(), "detection-agent"), correlation_id="test")

    # Attempting to invoke an unregistered dangerous tool raises UnknownToolError
    dangerous_tools = ["shell_exec", "isolate_host", "drop_table", "grant_role"]
    for tool_name in dangerous_tools:
        call = ToolCall(id=f"call-{tool_name}", name=tool_name, arguments={})
        with pytest.raises(UnknownToolError):
            await reg.invoke(call, ctx)


@pytest.mark.security
def test_proposed_actions_enforce_human_approval_gate() -> None:
    """In suggest_only mode, all proposed actions are blocked from autonomous execution."""
    proposal = ProposedAction(
        action_type="network_isolate",
        target="host-192.168.1.50",
        rationale="Lateral movement observed",
        reversible=True,
    )
    # Under suggest_only mode: automatic execution is denied
    decision_suggest = action_gate(
        proposal,
        response_mode="suggest_only",
        approval_required=True,
        is_production=True,
        policy_signed=False,
    )
    assert decision_suggest == "denied"

    # Even in auto mode, if approval_required is True, verdict must be approval_required, never allowed
    decision_needs_approval = action_gate(
        proposal,
        response_mode="auto",
        approval_required=True,
        is_production=True,
        policy_signed=True,
    )
    assert decision_needs_approval == "approval_required"


@pytest.mark.security
def test_unknown_agent_names_are_rejected() -> None:
    """The agent runner only recognizes the vetted defense agents."""
    valid_agents = set(_SPECS.keys())
    assert "arbitrary_agent" not in valid_agents
    assert "eval_agent" not in valid_agents
    assert valid_agents == {
        "detection-agent",
        "threat-intel-agent",
        "response-orchestration-agent",
    }