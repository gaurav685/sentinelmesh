from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sm_ai_analyst.agents import AgentRunner
from sm_ai_analyst.analyst import IncidentAnalyst
from sm_ai_analyst.app import create_app
from sm_ai_analyst.deps import Services
from sm_ai_analyst.hunt import HuntPlanner
from sm_ai_analyst.metrics import AnalystMetrics
from sm_ai_analyst.narrative import NarrativeComposer
from sm_common.observability import build_metrics

from .conftest import FakeChainsClient, FakeDb, FakeNarrativeRepository, build_chain, build_settings, token


@pytest.fixture
def chains() -> FakeChainsClient:
    return FakeChainsClient()


@pytest.fixture
def client(chains: FakeChainsClient) -> Any:
    base = build_metrics("ai-analyst")
    settings = build_settings()
    services = Services(
        settings=settings,
        metrics=base,
        analyst_metrics=AnalystMetrics(base, "ai-analyst"),
        analyst=IncidentAnalyst(None, model="m", max_output_tokens=200),
        agent_runner=AgentRunner(None, model="m", settings=settings),
        hunt_planner=HuntPlanner(None, model="m"),
        llm=None,
        llm_live_capable=False,
        db=FakeDb(),  # type: ignore[arg-type]
        http=None,  # type: ignore[arg-type]
        chains=chains,  # type: ignore[arg-type]
        narrative_repo=FakeNarrativeRepository(),  # type: ignore[arg-type]
        narrative_composer=NarrativeComposer(None, model="m", max_output_tokens=200),
    )
    with TestClient(create_app(services=services)) as c:
        yield c


def test_narrative_requires_an_internal_token(client: TestClient) -> None:
    r = client.get(f"/api/v1/incidents/{uuid.uuid4()}/narrative")
    assert r.status_code == 401


def test_narrative_404_when_the_chain_is_not_found(client: TestClient, chains: FakeChainsClient) -> None:
    chains.chain_response = None
    r = client.get(
        f"/api/v1/incidents/{uuid.uuid4()}/narrative",
        headers={"Authorization": f"Bearer {token()}"},
    )
    assert r.status_code == 404


def test_narrative_returns_a_grounded_walkthrough(client: TestClient, chains: FakeChainsClient) -> None:
    chain = build_chain()
    chains.chain_response = chain
    r = client.get(
        f"/api/v1/incidents/{chain.id}/narrative",
        headers={"Authorization": f"Bearer {token()}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["chain_id"] == str(chain.id)
    assert body["beats"][0]["stage"] == "initial_access"
    assert body["degraded"] is True  # no LLM configured in this fixture
    assert body["simulated"] is False


def test_narrative_labels_a_simulated_chain(client: TestClient, chains: FakeChainsClient) -> None:
    chain = build_chain(subject_id="sim-host-01")
    chains.chain_response = chain
    r = client.get(
        f"/api/v1/incidents/{chain.id}/narrative",
        headers={"Authorization": f"Bearer {token()}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["simulated"] is True
    assert all(b["tier"] == "synthetic" for b in body["beats"])
