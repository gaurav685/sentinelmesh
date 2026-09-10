from __future__ import annotations

import uuid
from typing import Any

from .conftest import internal_token

TENANT = uuid.uuid4()


def _auth(tenant: Any = TENANT, **kw: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {internal_token(tenant, **kw)}"}


def test_query_requires_a_bearer_token(app_client: Any) -> None:
    r = app_client.get("/api/v1/graph/entity", params={"label": ":Host", "key": "web01"})
    assert r.status_code == 401


def test_query_rejects_a_token_for_another_audience(app_client: Any) -> None:
    r = app_client.get(
        "/api/v1/graph/entity",
        params={"label": ":Host", "key": "web01"},
        headers=_auth(audience="api-gateway"),
    )
    assert r.status_code == 401


def test_query_rejects_a_token_signed_with_the_wrong_key(app_client: Any) -> None:
    r = app_client.get(
        "/api/v1/graph/entity",
        params={"label": ":Host", "key": "web01"},
        headers=_auth(key="not-the-key"),
    )
    assert r.status_code == 401


def test_entity_uses_the_tenant_from_the_token_not_the_query(app_client: Any) -> None:
    app_client.fake_graph.read_plan = [
        [{"id": "n1", "labels": ["Host"], "props": {"host_id": "web01", "uid": "z"}}]
    ]
    r = app_client.get(
        "/api/v1/graph/entity",
        params={"label": ":Host", "key": "web01", "tenant_id": str(uuid.uuid4())},
        headers=_auth(),
    )
    assert r.status_code == 200
    assert r.json()["entity"]["properties"] == {"host_id": "web01"}
    # the query ran against the token's tenant, ignoring the bogus query param
    _cypher, params = app_client.fake_graph.reads[0]
    assert params["tenant"] == str(TENANT)


def test_entity_404_when_missing(app_client: Any) -> None:
    r = app_client.get(
        "/api/v1/graph/entity", params={"label": ":Host", "key": "ghost"}, headers=_auth()
    )
    assert r.status_code == 404


# ---- hunt ----------------------------------------------------------------
def _plan(intent: str, *selectors: tuple[str, str], **kw: Any) -> dict[str, Any]:
    return {
        "intent": intent,
        "selectors": [{"type": t, "value": v} for t, v in selectors],
        **kw,
    }


def test_hunt_requires_a_bearer_token(app_client: Any) -> None:
    r = app_client.post("/api/v1/graph/hunt", json=_plan("find_entity", ("host", "web01")))
    assert r.status_code == 401


def test_hunt_runs_a_validated_plan_scoped_to_the_token_tenant(app_client: Any) -> None:
    app_client.fake_graph.read_plan = [
        [{"id": "n1", "labels": ["Host"], "props": {"host_id": "web01", "uid": "z"}}]
    ]
    r = app_client.post(
        "/api/v1/graph/hunt",
        json=_plan("find_entity", ("host", "web01")),
        headers=_auth(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "find_entity"
    assert body["rows"][0]["properties"] == {"host_id": "web01"}
    assert body["cypher_fingerprint"]
    cypher, params = app_client.fake_graph.reads[-1]
    assert params["tenant"] == str(TENANT)
    assert "web01" not in cypher and params["v0"] == "web01"


def test_hunt_rejects_a_plan_outside_the_capability_set(app_client: Any) -> None:
    r = app_client.post(
        "/api/v1/graph/hunt",
        json=_plan("path_between", ("host", "web01")),  # needs 2 selectors
        headers=_auth(),
    )
    assert r.status_code == 422


def test_hunt_rejects_an_unknown_intent_at_the_schema(app_client: Any) -> None:
    r = app_client.post(
        "/api/v1/graph/hunt",
        json=_plan("delete_everything", ("host", "web01")),
        headers=_auth(),
    )
    assert r.status_code == 422


def test_hunt_rejects_a_stray_tenant_field_in_the_body(app_client: Any) -> None:
    body = _plan("find_entity", ("host", "web01"))
    body["tenant_id"] = str(uuid.uuid4())  # SmBaseModel extra=forbid
    r = app_client.post("/api/v1/graph/hunt", json=body, headers=_auth())
    assert r.status_code == 422


def test_bad_label_is_a_422(app_client: Any) -> None:
    r = app_client.get(
        "/api/v1/graph/entity", params={"label": ":Wormhole", "key": "x"}, headers=_auth()
    )
    assert r.status_code == 422


def test_neighbors_returns_the_view_shape(app_client: Any) -> None:
    app_client.fake_graph.read_plan = [
        [{"id": "a", "labels": ["Host"], "props": {"host_id": "web01"}}],
        [{"src": "a", "dst": "b", "type": "CONNECTED_TO", "props": {"port": 443}}],
    ]
    r = app_client.get(
        "/api/v1/graph/neighbors",
        params={"label": ":Host", "key": "web01", "depth": 2},
        headers=_auth(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["depth"] == 2
    assert body["nodes"][0]["labels"] == ["Host"]
    assert body["edges"][0]["type"] == "CONNECTED_TO"
    assert body["truncated"] is False


def test_paths_reports_not_found(app_client: Any) -> None:
    r = app_client.get(
        "/api/v1/graph/paths",
        params={
            "src_label": ":Host", "src_key": "a",
            "dst_label": ":Host", "dst_key": "b",
        },
        headers=_auth(),
    )
    assert r.status_code == 200
    assert r.json()["found"] is False
