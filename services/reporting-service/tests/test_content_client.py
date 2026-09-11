from __future__ import annotations

import uuid

import httpx
import pytest
import respx

from sm_common.errors import DependencyUnavailable
from sm_reporting_service.content_client import ContentClient

pytestmark = pytest.mark.asyncio

_GRAPH_URL = "http://graph.test"
_MITRE_URL = "http://mitre.test"
_AI_URL = "http://ai.test"
_MEMORY_URL = "http://memory.test"


def _client() -> ContentClient:
    return ContentClient(
        httpx.AsyncClient(), signing_key="k" * 40,
        graph_url=_GRAPH_URL, mitre_url=_MITRE_URL, ai_analyst_url=_AI_URL, memory_url=_MEMORY_URL,
    )


@respx.mock
async def test_graph_neighbors_returns_the_parsed_body():
    respx.get(f"{_GRAPH_URL}/api/v1/graph/neighbors").mock(
        return_value=httpx.Response(200, json={"root_id": "web01", "depth": 1, "nodes": [], "edges": []})
    )
    result = await _client().graph_neighbors(uuid.uuid4(), label="Host", key="web01")
    assert result is not None
    assert result["root_id"] == "web01"


@respx.mock
async def test_a_404_is_reported_as_none_not_an_outage():
    respx.get(f"{_GRAPH_URL}/api/v1/graph/neighbors").mock(return_value=httpx.Response(404))
    assert await _client().graph_neighbors(uuid.uuid4(), label="Host", key="missing") is None


@respx.mock
async def test_a_5xx_is_dependency_unavailable():
    respx.get(f"{_MITRE_URL}/api/v1/mitre/techniques").mock(return_value=httpx.Response(503))
    with pytest.raises(DependencyUnavailable):
        await _client().mitre_techniques(uuid.uuid4())


@respx.mock
async def test_a_connection_error_is_dependency_unavailable():
    respx.post(f"{_AI_URL}/api/v1/analyst/explain").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(DependencyUnavailable):
        await _client().explain(uuid.uuid4(), {"subject_type": "detection"})


@respx.mock
async def test_memory_patterns_round_trips():
    respx.get(f"{_MEMORY_URL}/api/v1/memory/patterns").mock(
        return_value=httpx.Response(200, json=[{"id": "p1", "technique_ids": ["T1110"]}])
    )
    result = await _client().memory_patterns(uuid.uuid4(), subject_type="host", subject_id="web01")
    assert result == [{"id": "p1", "technique_ids": ["T1110"]}]


@respx.mock
async def test_every_call_carries_a_bearer_token():
    route = respx.get(f"{_MITRE_URL}/api/v1/mitre/techniques").mock(
        return_value=httpx.Response(200, json=[])
    )
    await _client().mitre_techniques(uuid.uuid4())
    assert route.calls.last.request.headers["authorization"].startswith("Bearer ")
