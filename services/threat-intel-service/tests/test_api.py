from __future__ import annotations

import json
from typing import Any

from .conftest import token


def _auth(**kw: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(**kw)}"}


def test_enrich_requires_a_token(client: Any) -> None:
    assert client.post("/api/v1/ti/enrich", json={"items": [{"type": "ipv4", "value": "1.2.3.4"}]}).status_code == 401


def test_enrich_rejects_a_token_for_another_audience(client: Any) -> None:
    r = client.post(
        "/api/v1/ti/enrich", json={"items": [{"type": "ipv4", "value": "1.2.3.4"}]},
        headers=_auth(audience="mitre-service"),
    )
    assert r.status_code == 401


def test_submit_then_enrich_matches(client: Any) -> None:
    sub = client.post(
        "/api/v1/ti/indicators",
        json={"type": "ipv4", "value": "9.9.9.9", "confidence": "high", "tags": ["c2"]},
        headers=_auth(),
    )
    assert sub.status_code == 201
    assert sub.json()["action"] == "added"
    assert client.fake_producer.sent[0][0] == "ti.updates"

    enr = client.post(
        "/api/v1/ti/enrich", json={"items": [{"type": "ipv4", "value": "9.9.9.9"},
                                             {"type": "ipv4", "value": "1.1.1.1"}]},
        headers=_auth(),
    )
    results = enr.json()["results"]
    assert results[0]["matched"] is True
    assert results[1]["matched"] is False


def test_submit_rejects_a_malformed_value(client: Any) -> None:
    r = client.post(
        "/api/v1/ti/indicators", json={"type": "ipv4", "value": "not-an-ip"}, headers=_auth(),
    )
    assert r.status_code == 422
    assert "invalid ipv4" in json.dumps(r.json())


def test_healthz_and_metrics(client: Any) -> None:
    assert client.get("/healthz").json()["service"] == "threat-intel-service"
    assert "sm_ti_indicator_upserts_total" in client.get("/metrics").text
