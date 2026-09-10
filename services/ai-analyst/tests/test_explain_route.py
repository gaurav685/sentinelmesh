from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from sm_ai_analyst.agents import AgentRunner
from sm_ai_analyst.analyst import IncidentAnalyst
from sm_ai_analyst.app import create_app
from sm_ai_analyst.deps import Services
from sm_ai_analyst.metrics import AnalystMetrics
from sm_common.observability import build_metrics

from .conftest import build_settings, canned_client, make_request, token


@pytest.fixture
def client() -> Any:
    base = build_metrics("ai-analyst")
    am = AnalystMetrics(base, "ai-analyst")
    settings = build_settings()
    analyst = IncidentAnalyst(
        canned_client("Repeated failed logins [det-1] indicate brute force [T1110]."),
        model="test-model",
        max_output_tokens=400,
    )
    from sm_ai_analyst.hunt import HuntPlanner

    services = Services(
        settings=settings,
        metrics=base,
        analyst_metrics=am,
        analyst=analyst,
        agent_runner=AgentRunner(None, model="test-model", settings=settings),
        hunt_planner=HuntPlanner(None, model="test-model"),
        llm=None,
        llm_live_capable=False,
    )
    with TestClient(create_app(services=services)) as c:
        yield c


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {token()}"}


def test_explain_requires_an_internal_token(client: TestClient) -> None:
    r = client.post("/api/v1/analyst/explain", json=make_request().model_dump(mode="json"))
    assert r.status_code == 401


def test_explain_rejects_a_token_for_the_wrong_audience(client: TestClient) -> None:
    r = client.post(
        "/api/v1/analyst/explain",
        headers={"Authorization": f"Bearer {token(audience='mitre-service')}"},
        json=make_request().model_dump(mode="json"),
    )
    assert r.status_code == 401


def test_explain_returns_a_grounded_explanation(client: TestClient) -> None:
    r = client.post(
        "/api/v1/analyst/explain",
        headers=_auth(),
        json=make_request().model_dump(mode="json"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["degraded"] is False
    assert sorted(body["cited_refs"]) == ["T1110", "det-1"]
    assert body["recommendations"]


def test_readyz_reports_template_only_mode(client: TestClient) -> None:
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["dependencies"][0]["detail"] == "template-only"
