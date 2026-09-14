"""ml-inference service contracts — no model artifact required.

Verifies the degraded path honestly: a missing artifact is a typed 503
(`MODEL_UNAVAILABLE`), never a 500 and never a fabricated score; the error
body matches the canonical error contract; and every response carries a
`model_version` field.

These tests live in `tests/ml/` (repo-root) alongside the service's own
`test_infer.py`; they assert the *contract* properties the Constitution's ML
review flagged — the 503 body shape, the absence of a fabricated score in the
degraded path, and the presence of `model_version` on every response.
"""

from __future__ import annotations

from typing import Any

from sm_contracts import CanonicalKind
from sm_ml import schema_for

from .conftest import auth, write_statistical_artifact

_KIND = CanonicalKind.auth
_N = len(schema_for(_KIND).names)


def _body(features: list[float] | None = None) -> dict[str, Any]:
    return {
        "kind": _KIND.value,
        "feature_schema_version": schema_for(_KIND).version,
        "features": features if features is not None else [0.0] * _N,
    }


def test_missing_artifact_is_503_not_500_and_not_a_fabricated_score(
    client: Any, model_dir
) -> None:
    r = client.post("/api/v1/infer/does-not-exist", json=_body(), headers=auth())
    assert r.status_code == 503, r.text
    error = r.json()["error"]
    assert error["code"] == "dependency_unavailable"
    assert "MODEL_UNAVAILABLE" in error["message"]
    # The canonical error contract carries a `details` list with the field.
    assert any(d.get("field") == "model" for d in error.get("details", []))


def test_degraded_mode_is_honest_and_not_a_fabricated_score(
    client: Any, model_dir
) -> None:
    """No artifact at all means no model; the response must not invent a score."""
    r = client.post("/api/v1/infer/absent", json=_body(), headers=auth())
    assert r.status_code == 503
    assert "score" not in r.json()


def test_error_body_matches_the_canonical_error_contract(
    client: Any, model_dir
) -> None:
    r = client.post("/api/v1/infer/absent", json=_body(), headers=auth())
    error = r.json()["error"]
    for field in ("code", "message"):
        assert field in error, f"error body missing {field!r}"
    assert isinstance(error["message"], str) and error["message"]


def test_a_registered_model_returns_a_model_version_field(
    client: Any, model_dir
) -> None:
    write_statistical_artifact(model_dir, "baseline_auth", _KIND)
    r = client.post(
        "/api/v1/infer/baseline_auth", json=_body([1.0] * _N), headers=auth()
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert "model_version" in payload
    # `model_version` is the contract field; it is `None` for a freshly-fit
    # statistical model with no registered version, which is an honest value
    # (not a fabricated one) — the field is present either way.
    assert payload["model_version"] is None or isinstance(payload["model_version"], str)


def test_models_endpoint_lists_registered_models(
    client: Any, model_dir
) -> None:
    write_statistical_artifact(model_dir, "baseline_auth", _KIND)
    r = client.get("/api/v1/models", headers=auth())
    assert r.status_code == 200
    names = [m["name"] for m in r.json()["models"]]
    assert "baseline_auth" in names