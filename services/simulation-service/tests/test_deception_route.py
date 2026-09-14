from __future__ import annotations

from typing import Any

from .conftest import token

_DECOYS = "/api/v1/deception/decoys"


def _headers() -> dict[str, str]:
    return {"authorization": f"Bearer {token()}"}


def _register(client: Any, headers: dict[str, str], **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"name": "ssh-honeypot", "kind": "honeypot_host", "network_boundary": "isolated"}
    body.update(over)
    resp = client.post(_DECOYS, json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_production_network_boundary_is_schema_rejected(client: Any) -> None:
    resp = client.post(
        _DECOYS,
        json={"name": "x", "kind": "honeypot_host", "network_boundary": "production"},
        headers=_headers(),
    )
    assert resp.status_code == 422


def test_register_then_list_then_get(client: Any) -> None:
    headers = _headers()
    decoy = _register(client, headers)
    assert decoy["status"] == "active"
    assert decoy["network_boundary"] == "isolated"

    listed = client.get(_DECOYS, headers=headers).json()
    assert any(d["id"] == decoy["id"] for d in listed)

    got = client.get(f"{_DECOYS}/{decoy['id']}", headers=headers)
    assert got.status_code == 200
    assert got.json()["id"] == decoy["id"]


def test_get_missing_decoy_is_404(client: Any) -> None:
    resp = client.get(f"{_DECOYS}/00000000-0000-0000-0000-000000000000", headers=_headers())
    assert resp.status_code == 404


def test_teardown_is_idempotent(client: Any) -> None:
    headers = _headers()
    decoy = _register(client, headers)
    first = client.delete(f"{_DECOYS}/{decoy['id']}", headers=headers)
    assert first.status_code == 200
    assert first.json()["status"] == "torn_down"

    second = client.delete(f"{_DECOYS}/{decoy['id']}", headers=headers)
    assert second.status_code == 200
    assert second.json()["status"] == "torn_down"


def test_teardown_missing_decoy_is_404(client: Any) -> None:
    resp = client.delete(f"{_DECOYS}/00000000-0000-0000-0000-000000000000", headers=_headers())
    assert resp.status_code == 404


def test_interaction_captured_on_active_decoy(client: Any) -> None:
    headers = _headers()
    decoy = _register(client, headers)
    resp = client.post(
        f"{_DECOYS}/{decoy['id']}/interactions",
        json={"source": "10.0.0.9", "technique_hint": "T1110", "detail": {"port": "22"}},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["source"] == "10.0.0.9"

    listed = client.get(f"{_DECOYS}/{decoy['id']}/interactions", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_torn_down_decoy_captures_nothing_further(client: Any) -> None:
    headers = _headers()
    decoy = _register(client, headers)
    client.delete(f"{_DECOYS}/{decoy['id']}", headers=headers)
    resp = client.post(
        f"{_DECOYS}/{decoy['id']}/interactions", json={"source": "10.0.0.9"}, headers=headers,
    )
    assert resp.status_code == 404


def test_list_decoys_respects_limit(client: Any) -> None:
    headers = _headers()
    _register(client, headers, name="decoy-limit-1")
    _register(client, headers, name="decoy-limit-2")
    resp = client.get(f"{_DECOYS}?limit=1", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
