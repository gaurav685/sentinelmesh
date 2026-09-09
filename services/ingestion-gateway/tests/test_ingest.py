from __future__ import annotations

import hashlib
from typing import Any

import pytest
from fastapi.testclient import TestClient


def test_valid_flow_is_accepted_and_envelope_is_server_built(
    client: TestClient, rig: Any, auth_header: dict[str, str], flow: Any,
    sensor_id: Any, tenant_id: Any,
) -> None:
    r = client.post("/api/v1/ingest/network_flow", json=flow(), headers=auth_header)
    assert r.status_code == 202
    event_id = r.json()["event_id"]
    assert event_id

    assert len(rig.raw.events) == 1
    env = rig.raw.events[0]
    assert str(env.event_id) == event_id
    assert env.tenant_id == tenant_id  # from the sensor identity, not the body
    assert env.source.type.value == "sensor"
    assert env.source.sensor_id == sensor_id
    assert env.producer.startswith("ingestion-gateway@")
    assert env.partition_key == hashlib.sha256(f"{tenant_id}:10.0.0.1".encode()).hexdigest()[:16]
    assert env.payload.protocol == "tcp"


@pytest.mark.parametrize(
    ("source_type", "body"),
    [
        ("auth_event", {"outcome": "success", "auth_type": "ssh", "principal": "alice@corp"}),
        ("dns_query", {"client_ip": "10.0.0.5", "query_name": "example.com", "query_type": "a"}),
        ("process_exec", {"host": "web01", "process_name": "curl"}),
        ("file_access", {"host": "web01", "path": "/etc/passwd", "action": "read"}),
    ],
)
def test_each_source_type_accepts_its_payload(
    client: TestClient, rig: Any, auth_header: dict[str, str],
    source_type: str, body: dict[str, Any], now_iso: str,
) -> None:
    r = client.post(
        f"/api/v1/ingest/{source_type}", json={"occurred_at": now_iso, **body}, headers=auth_header
    )
    assert r.status_code == 202
    assert len(rig.raw.events) == 1
    assert rig.raw.events[0].event_type.value == f"telemetry.{source_type}"


def test_missing_authorization_is_401(client: TestClient, flow: Any) -> None:
    r = client.post("/api/v1/ingest/network_flow", json=flow())
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


def test_unknown_sensor_is_generic_401(
    client: TestClient, flow: Any, sensor_id: Any
) -> None:
    r = client.post(
        "/api/v1/ingest/network_flow", json=flow(),
        headers={"authorization": f"{sensor_id}.wrong-secret"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


def test_unknown_source_type_is_404(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post("/api/v1/ingest/keystrokes", json={"x": 1}, headers=auth_header)
    assert r.status_code == 404


def test_malformed_payload_is_422_and_dead_lettered(
    client: TestClient, rig: Any, auth_header: dict[str, str], flow: Any, sensor_id: Any
) -> None:
    r = client.post(
        "/api/v1/ingest/network_flow", json=flow(src_ip="not-an-ip"), headers=auth_header
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert not rig.raw.events
    assert len(rig.dlq.items) == 1
    assert rig.dlq.items[0]["reason"] == "schema_validation"
    assert rig.dlq.items[0]["sensor_id"] == sensor_id


def test_extra_field_in_body_is_rejected(
    client: TestClient, rig: Any, auth_header: dict[str, str], flow: Any
) -> None:
    # A sensor cannot smuggle a tenant_id (or anything else) into the payload.
    r = client.post(
        "/api/v1/ingest/network_flow",
        json=flow(tenant_id="00000000-0000-0000-0000-000000000000"),
        headers=auth_header,
    )
    assert r.status_code == 422
    assert len(rig.dlq.items) == 1


def test_invalid_json_is_422_and_dead_lettered(
    client: TestClient, rig: Any, auth_header: dict[str, str]
) -> None:
    r = client.post(
        "/api/v1/ingest/network_flow", content=b"{not json",
        headers={**auth_header, "content-type": "application/json"},
    )
    assert r.status_code == 422
    assert rig.dlq.items[0]["reason"] == "invalid_json"


def test_oversized_body_is_413(client: TestClient, auth_header: dict[str, str]) -> None:
    # Default SM_HTTP_MAX_BODY_BYTES is 1 MiB; send more.
    oversized = b'{"occurred_at":"' + b"x" * 1_200_000 + b'"}'
    r = client.post(
        "/api/v1/ingest/network_flow", content=oversized,
        headers={**auth_header, "content-type": "application/json"},
    )
    assert r.status_code == 413


def test_duplicate_client_event_id_is_idempotent(
    client: TestClient, rig: Any, auth_header: dict[str, str], flow: Any
) -> None:
    headers = {**auth_header, "x-sensor-event-id": "evt-1"}
    first = client.post("/api/v1/ingest/network_flow", json=flow(), headers=headers)
    assert first.status_code == 202
    assert len(rig.raw.events) == 1

    second = client.post("/api/v1/ingest/network_flow", json=flow(), headers=headers)
    assert second.status_code == 200
    assert second.json() == {"event_id": None, "deduplicated": True}
    assert len(rig.raw.events) == 1  # not re-sunk


def test_rate_limiter_fails_closed_with_503(
    client: TestClient, rig: Any, auth_header: dict[str, str], flow: Any
) -> None:
    rig.cache.client.healthy = False
    r = client.post("/api/v1/ingest/network_flow", json=flow(), headers=auth_header)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "dependency_unavailable"


def test_rate_limit_returns_429_after_the_window_limit(
    client: TestClient, auth_header: dict[str, str], flow: Any
) -> None:
    # settings.rate_limit_per_minute == 5 in the test rig.
    codes = [
        client.post("/api/v1/ingest/network_flow", json=flow(), headers=auth_header).status_code
        for _ in range(7)
    ]
    assert codes.count(202) == 5
    assert codes.count(429) == 2


def test_batch_accepts_good_and_dead_letters_bad(
    client: TestClient, rig: Any, auth_header: dict[str, str], flow: Any
) -> None:
    body = {
        "source_type": "network_flow",
        "events": [flow(), flow(src_ip="nope"), flow(dst_port=443)],
    }
    r = client.post("/api/v1/ingest/batch", json=body, headers=auth_header)
    assert r.status_code == 202
    payload = r.json()
    assert payload["accepted"] == 2
    assert payload["rejected"] == [{"index": 1, "reason": "schema_validation"}]
    assert len(payload["event_ids"]) == 2
    assert len(rig.raw.events) == 2
    assert len(rig.dlq.items) == 1


def test_batch_over_the_limit_is_422(
    client: TestClient, rig: Any, auth_header: dict[str, str], flow: Any, settings_builder: Any
) -> None:
    rig.services.settings = settings_builder(ingest_batch_max_events=2, rate_limit_per_minute=50)
    body = {"source_type": "network_flow", "events": [flow() for _ in range(3)]}
    r = client.post("/api/v1/ingest/batch", json=body, headers=auth_header)
    assert r.status_code == 422


def test_raw_sink_failure_fails_the_request_with_503(
    client: TestClient, rig: Any, auth_header: dict[str, str], flow: Any
) -> None:
    rig.raw.fail = True
    r = client.post("/api/v1/ingest/network_flow", json=flow(), headers=auth_header)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "dependency_unavailable"


def test_dlq_sink_failure_does_not_mask_the_422(
    client: TestClient, rig: Any, auth_header: dict[str, str], flow: Any
) -> None:
    rig.dlq.fail = True
    r = client.post("/api/v1/ingest/network_flow", json=flow(src_ip="bad"), headers=auth_header)
    assert r.status_code == 422  # the client error survives a second sink failure


def test_batch_raw_sink_failure_aborts_with_503(
    client: TestClient, rig: Any, auth_header: dict[str, str], flow: Any
) -> None:
    rig.raw.fail = True
    body = {"source_type": "network_flow", "events": [flow(), flow()]}
    r = client.post("/api/v1/ingest/batch", json=body, headers=auth_header)
    assert r.status_code == 503
