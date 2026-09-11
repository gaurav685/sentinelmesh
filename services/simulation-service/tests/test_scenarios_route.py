from __future__ import annotations

from typing import Any

from .conftest import token

_RUN = "/api/v1/sim/scenarios/run"


def _req(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "drill", "kind": "brute_force", "seed": 1,
        "target_host": "sim-host-00", "target_identity": "sim-id-alice", "intensity": 2,
    }
    body.update(over)
    return body


def test_no_bearer_token_is_unauthenticated(client: Any) -> None:
    resp = client.post(_RUN, json=_req())
    assert resp.status_code == 401


def test_a_valid_scenario_runs_deterministically(client: Any) -> None:
    headers = {"authorization": f"Bearer {token()}"}
    resp = client.post(_RUN, json=_req(), headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["synthetic"] is True
    assert body["fed_to_pipeline"] is False
    assert body["fed_event_count"] == 0
    assert body["event_count"] == len(body["events"]) > 0
    assert all(e["scenario_id"] == body["scenario_id"] for e in body["events"])

    resp2 = client.post(_RUN, json=_req(), headers=headers)
    assert resp2.json()["scenario_id"] == body["scenario_id"]
    assert resp2.json()["events"] == body["events"]


def test_non_synthetic_target_is_refused(client: Any) -> None:
    headers = {"authorization": f"Bearer {token()}"}
    resp = client.post(_RUN, json=_req(target_host="prod-host-01"), headers=headers)
    assert resp.status_code == 422


def test_unknown_synthetic_target_is_refused(client: Any) -> None:
    headers = {"authorization": f"Bearer {token()}"}
    resp = client.post(_RUN, json=_req(target_host="sim-host-99"), headers=headers)
    assert resp.status_code == 422


def test_feed_pipeline_without_event_bus_is_refused(client_no_bus: Any) -> None:
    headers = {"authorization": f"Bearer {token()}"}
    resp = client_no_bus.post(_RUN, json=_req(feed_pipeline=True), headers=headers)
    assert resp.status_code == 422


def test_feed_pipeline_produces_onto_telemetry_raw(client: Any, producer: Any) -> None:
    headers = {"authorization": f"Bearer {token()}"}
    resp = client.post(_RUN, json=_req(feed_pipeline=True), headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["fed_to_pipeline"] is True
    assert body["fed_event_count"] > 0
    assert len(producer.sent) == body["fed_event_count"]
    assert all(topic == "telemetry.raw" for topic, _key, _value in producer.sent)
