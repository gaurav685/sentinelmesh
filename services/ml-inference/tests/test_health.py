from __future__ import annotations

from pathlib import Path
from typing import Any

from sm_contracts import CanonicalKind

from .conftest import write_statistical_artifact


def test_healthz(client: Any) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["service"] == "ml-inference"


def test_readyz_is_ready_with_no_models(client: Any) -> None:
    r = client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is True
    assert body["dependencies"][0]["detail"] == "0 registered, 0 loaded"


def test_readyz_reports_the_catalog(client: Any, model_dir: Path) -> None:
    write_statistical_artifact(model_dir, "baseline_auth", CanonicalKind.auth)
    detail = client.get("/readyz").json()["dependencies"][0]["detail"]
    assert detail.startswith("1 registered")


def test_health_deps_mirrors_readyz(client: Any) -> None:
    r = client.get("/health/deps")
    assert r.status_code == 200
    assert r.json()["dependencies"][0]["detail"] == "0 registered, 0 loaded"


def test_meta_and_metrics(client: Any) -> None:
    assert client.get("/api/v1/meta").json()["service"] == "ml-inference"
    assert "sm_inference_requests_total" in client.get("/metrics").text
