from __future__ import annotations

from typing import Any

from .conftest import token

_TWIN = "/api/v1/sim/twin"


def test_no_bearer_token_is_unauthenticated(client: Any) -> None:
    assert client.get(_TWIN).status_code == 401


def test_twin_snapshot_is_deterministic_for_the_same_seed(client: Any) -> None:
    headers = {"authorization": f"Bearer {token()}"}
    first = client.get(f"{_TWIN}?seed=1", headers=headers)
    second = client.get(f"{_TWIN}?seed=1", headers=headers)
    assert first.status_code == 200
    assert first.json() == second.json()
    assert first.json()["synthetic"] is True
    assert first.json()["assets"]


def test_twin_snapshot_differs_by_seed(client: Any) -> None:
    headers = {"authorization": f"Bearer {token()}"}
    a = client.get(f"{_TWIN}?seed=1", headers=headers).json()
    b = client.get(f"{_TWIN}?seed=2", headers=headers).json()
    assert a["seed"] != b["seed"]


def test_blast_radius_reaches_beyond_the_seed_asset(client: Any) -> None:
    headers = {"authorization": f"Bearer {token()}"}
    snapshot = client.get(f"{_TWIN}?seed=1", headers=headers).json()
    web = next(a for a in snapshot["assets"] if "web" in a["tags"])
    resp = client.post(
        f"{_TWIN}/blast-radius",
        json={"seed": 1, "seeds": [web["id"]], "max_hops": 4},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["seeds"] == [web["id"]]
    assert len(body["reached"]) > 1
    assert 0.0 < body["score"] <= 1.0


def test_blast_radius_on_an_unknown_seed_reaches_nothing(client: Any) -> None:
    headers = {"authorization": f"Bearer {token()}"}
    resp = client.post(
        f"{_TWIN}/blast-radius",
        json={"seed": 1, "seeds": ["sim-host-99"], "max_hops": 4},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["seeds"] == []
    assert body["reached"] == []
    assert body["score"] == 0.0
