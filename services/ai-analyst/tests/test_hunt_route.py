from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from sm_ai import DeterministicAdapter
from sm_ai_analyst.agents import AgentRunner
from sm_ai_analyst.analyst import IncidentAnalyst
from sm_ai_analyst.app import create_app
from sm_ai_analyst.deps import Services
from sm_ai_analyst.hunt import HuntPlanner
from sm_ai_analyst.metrics import AnalystMetrics
from sm_common.observability import build_metrics

from .conftest import build_client, build_settings, token

_VALID_PLAN_JSON = (
    '{"intent": "list_related", "selectors": [{"type": "host", "value": "web01"}], '
    '"rel_types": [], "limits": {"max_depth": 2, "max_rows": 100}}'
)


@pytest.fixture
def client() -> Any:
    base = build_metrics("ai-analyst")
    settings = build_settings()
    planner = HuntPlanner(build_client(DeterministicAdapter.canned(_VALID_PLAN_JSON)), model="m")
    services = Services(
        settings=settings,
        metrics=base,
        analyst_metrics=AnalystMetrics(base, "ai-analyst"),
        analyst=IncidentAnalyst(None, model="m", max_output_tokens=200),
        agent_runner=AgentRunner(None, model="m", settings=settings),
        hunt_planner=planner,
        llm=None,
        llm_live_capable=False,
    )
    with TestClient(create_app(services=services)) as c:
        yield c


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {token()}"}


def test_hunt_plan_requires_an_internal_token(client: TestClient) -> None:
    assert client.post("/api/v1/hunt/plan", json={"query": "x"}).status_code == 401


def test_hunt_plan_translates_nl_to_a_query_plan(client: TestClient) -> None:
    r = client.post("/api/v1/hunt/plan", headers=_auth(), json={"query": "what talks to web01"})
    assert r.status_code == 200
    body = r.json()
    assert body["supported"] is True
    assert body["plan"]["intent"] == "list_related"


def test_hunt_explain_fills_a_deterministic_summary_without_an_llm(client: TestClient) -> None:
    result = {
        "intent": "find_entity",
        "plan": {
            "intent": "find_entity",
            "selectors": [{"type": "host", "value": "web01"}],
            "rel_types": [],
            "limits": {"max_depth": 2, "max_rows": 100},
        },
        "rows": [{"id": "n1", "labels": ["Host"], "properties": {"host_id": "web01"}}],
        "row_count": 1,
        "truncated": False,
        "cypher_fingerprint": "abc",
        "explanation": "",
    }
    r = client.post("/api/v1/hunt/explain", headers=_auth(), json={"result": result})
    assert r.status_code == 200
    body = r.json()
    assert "1 result" in body["explanation"]
    assert body["cypher_fingerprint"] == "abc"
