from __future__ import annotations

from pathlib import Path
from typing import Any

from sm_contracts import CanonicalKind
from sm_ml import schema_for

from .conftest import auth, write_statistical_artifact

_KIND = CanonicalKind.auth
_N = len(schema_for(_KIND).names)


def _body(features: list[float] | None = None, *, version: str | None = None) -> dict[str, Any]:
    return {
        "kind": _KIND.value,
        "feature_schema_version": version or schema_for(_KIND).version,
        "features": features if features is not None else [0.0] * _N,
    }


def test_infer_requires_a_bearer_token(client: Any) -> None:
    assert client.post("/api/v1/infer/whatever", json=_body()).status_code == 401


def test_infer_rejects_a_token_for_another_audience(client: Any) -> None:
    r = client.post("/api/v1/infer/whatever", json=_body(), headers=auth(audience="graph-service"))
    assert r.status_code == 401


def test_models_catalog_is_empty_without_artifacts(client: Any) -> None:
    r = client.get("/api/v1/models", headers=auth())
    assert r.status_code == 200
    assert r.json() == {"models": []}


def test_unknown_model_is_model_unavailable(client: Any) -> None:
    r = client.post("/api/v1/infer/isolation_forest", json=_body(), headers=auth())
    assert r.status_code == 503
    body = r.json()["error"]
    assert body["code"] == "dependency_unavailable"
    assert "MODEL_UNAVAILABLE" in body["message"]
    assert body["details"][0]["field"] == "model"


def test_feature_schema_version_mismatch_is_422(client: Any) -> None:
    r = client.post(
        "/api/v1/infer/baseline_auth", json=_body(version="99"), headers=auth()
    )
    assert r.status_code == 422
    assert "feature_schema_version" in r.json()["error"]["message"]


def test_wrong_feature_count_is_422(client: Any) -> None:
    r = client.post(
        "/api/v1/infer/baseline_auth", json=_body(features=[0.0, 0.0]), headers=auth()
    )
    assert r.status_code == 422


def test_serves_a_statistical_artifact(client: Any, model_dir: Path) -> None:
    write_statistical_artifact(model_dir, "baseline_auth", _KIND)

    catalog = client.get("/api/v1/models", headers=auth()).json()["models"]
    assert [m["name"] for m in catalog] == ["baseline_auth"]

    normal = client.post(
        "/api/v1/infer/baseline_auth", json=_body([1.0] * _N), headers=auth()
    )
    assert normal.status_code == 200
    payload = normal.json()
    assert payload["model"] == "baseline_auth"
    assert payload["method"] == "mad_zscore"
    assert 0.0 <= payload["normalized_score"] <= 1.0
    assert isinstance(payload["is_anomaly"], bool)

    outlier = client.post(
        "/api/v1/infer/baseline_auth",
        json=_body([500.0] + [1.0] * (_N - 1)),
        headers=auth(),
    ).json()
    assert outlier["is_anomaly"] is True
