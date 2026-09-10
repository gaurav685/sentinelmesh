from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from sm_ai import DeterministicAdapter, LlmResponse, ToolCall
from sm_ai_analyst.agents import AgentRunner
from sm_ai_analyst.analyst import IncidentAnalyst
from sm_ai_analyst.app import create_app
from sm_ai_analyst.deps import Services
from sm_ai_analyst.metrics import AnalystMetrics
from sm_common.observability import build_metrics
from sm_contracts import AgentRunRequest, EvidenceRef

from .conftest import build_client, build_settings, canned_client, token


def _req(agent: str) -> dict[str, Any]:
    return AgentRunRequest(
        agent=agent,  # type: ignore[arg-type]
        subject_type="detection",
        subject_id="det-1",
        task="Assess this detection.",
        evidence=[
            EvidenceRef(
                kind="detection", ref="det-1", provenance="detection-engine:x",
                content="12 failed logins for svc-backup",
            )
        ],
    ).model_dump(mode="json")


def _services(runner: AgentRunner) -> Services:
    base = build_metrics("ai-analyst")
    return Services(
        settings=build_settings(),
        metrics=base,
        analyst_metrics=AnalystMetrics(base, "ai-analyst"),
        analyst=IncidentAnalyst(None, model="m", max_output_tokens=200),
        agent_runner=runner,
        llm_live_capable=False,
    )


@pytest.fixture
def client_completing() -> Any:
    def handler(_req: Any) -> LlmResponse:
        return LlmResponse(text="- Repeated failed logins indicate brute force [det-1]")

    runner = AgentRunner(
        build_client(DeterministicAdapter(handler)), model="m", settings=build_settings()
    )
    with TestClient(create_app(services=_services(runner))) as c:
        yield c


def test_agents_run_requires_an_internal_token(client_completing: TestClient) -> None:
    assert client_completing.post("/api/v1/agents/run", json=_req("detection-agent")).status_code == 401


def test_the_detection_agent_returns_findings(client_completing: TestClient) -> None:
    r = client_completing.post(
        "/api/v1/agents/run",
        headers={"Authorization": f"Bearer {token()}"},
        json=_req("detection-agent"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["findings"][0]["evidence_refs"] == ["det-1"]


def test_a_proposed_action_is_gated_never_allowed(client_completing: TestClient) -> None:
    # this fixture's model does not propose; use a dedicated runner
    runner = AgentRunner(
        canned_client(
            "- Isolate the host [det-1]\nPROPOSE: isolate_host svc-backup :: brute force"
        ),
        model="m",
        settings=build_settings(),
    )
    with TestClient(create_app(services=_services(runner))) as c:
        r = c.post(
            "/api/v1/agents/run",
            headers={"Authorization": f"Bearer {token()}"},
            json=_req("response-orchestration-agent"),
        )
    assert r.status_code == 200
    actions = r.json()["proposed_actions"]
    assert actions and actions[0]["decision"] == "denied"


def test_an_agent_run_with_no_llm_reports_failed_not_500() -> None:
    runner = AgentRunner(None, model="m", settings=build_settings())
    with TestClient(create_app(services=_services(runner))) as c:
        r = c.post(
            "/api/v1/agents/run",
            headers={"Authorization": f"Bearer {token()}"},
            json=_req("detection-agent"),
        )
    assert r.status_code == 200
    assert r.json()["status"] == "failed"
    assert r.json()["detail"] == "llm_unavailable"


def test_a_tool_call_the_agent_is_not_allowed_does_not_break_the_run() -> None:
    step = {"n": 0}

    def handler(_req: Any) -> LlmResponse:
        step["n"] += 1
        if step["n"] == 1:
            return LlmResponse(
                text="", tool_calls=(ToolCall(id="c1", name="disable_user", arguments={}),)
            )
        return LlmResponse(text="- Nothing was disabled [det-1]")

    runner = AgentRunner(
        build_client(DeterministicAdapter(handler)), model="m", settings=build_settings()
    )
    with TestClient(create_app(services=_services(runner))) as c:
        r = c.post(
            "/api/v1/agents/run",
            headers={"Authorization": f"Bearer {token()}"},
            json=_req("detection-agent"),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["tool_calls_used"] == 1
