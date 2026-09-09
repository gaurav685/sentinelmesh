from __future__ import annotations

from typing import Any

from sm_ml.graph import GRAPH_FEATURE_SCHEMA_VERSION

from .conftest import auth


def _graph(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "graph_feature_schema_version": GRAPH_FEATURE_SCHEMA_VERSION,
        "nodes": [
            {"node_id": "hub", "node_type": "Host", "first_seen": 0.0, "last_seen": 100.0},
            {"node_id": "a", "node_type": "Identity", "first_seen": 1.0, "last_seen": 2.0},
            {"node_id": "b", "node_type": "Identity", "first_seen": 3.0, "last_seen": 4.0},
        ],
        "edges": [
            {"src_id": "a", "dst_id": "hub", "edge_type": "AUTHENTICATED_TO", "observed_at": 1.5},
            {"src_id": "b", "dst_id": "hub", "edge_type": "AUTHENTICATED_TO", "observed_at": 3.5},
        ],
    }
    body.update(over)
    return body


def test_graph_models_lists_the_builtin_structural(client: Any) -> None:
    r = client.get("/api/v1/graph/models", headers=auth())
    assert r.status_code == 200
    names = {m["name"] for m in r.json()}
    assert "structural" in names


def test_structural_graph_inference_scores_every_node(client: Any) -> None:
    r = client.post("/api/v1/infer/graph/structural", json=_graph(), headers=auth())
    assert r.status_code == 200
    body = r.json()
    assert body["method"] == "structural_zscore"
    assert {s["node_id"] for s in body["scores"]} == {"a", "b", "hub"}
    assert all(0.0 <= s["normalized_score"] <= 1.0 for s in body["scores"])
    assert body["feature_schema_version"] == GRAPH_FEATURE_SCHEMA_VERSION


def test_a_gnn_model_with_no_artifact_is_model_unavailable(client: Any) -> None:
    r = client.post("/api/v1/infer/graph/graphsage", json=_graph(), headers=auth())
    assert r.status_code == 503
    assert "MODEL_UNAVAILABLE" in r.json()["error"]["message"]


def test_schema_version_mismatch_is_422(client: Any) -> None:
    r = client.post(
        "/api/v1/infer/graph/structural",
        json=_graph(graph_feature_schema_version="999"), headers=auth(),
    )
    assert r.status_code == 422


def test_a_malformed_graph_is_422_not_500(client: Any) -> None:
    bad = _graph()
    bad["edges"].append(
        {"src_id": "a", "dst_id": "ghost", "edge_type": "X", "observed_at": 9.0}
    )
    r = client.post("/api/v1/infer/graph/structural", json=bad, headers=auth())
    assert r.status_code == 422


def test_graph_inference_requires_a_service_token(client: Any) -> None:
    assert client.post("/api/v1/infer/graph/structural", json=_graph()).status_code == 401
    assert client.get("/api/v1/graph/models").status_code == 401
