from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from sm_contracts import BenchmarkExperiment

_BASE = dict(
    dataset_id="nsl-kdd",
    train_sha256="a" * 64,
    test_sha256="b" * 64,
    preprocessing_version="nsl-kdd-v1",
    model_name="mad_zscore",
    n_train=125973,
    n_train_benign_used_for_fit=67343,
    n_test=22544,
    n_test_anomalous=12833,
    params={"z_threshold": 3.5, "n_features": 125},
    seed=1337,
    metrics={"roc_auc": 0.639039, "precision": 0.581191},
    environment={"python_version": "3.11.5"},
    executed=True,
    generated_at="2026-09-12T15:42:36Z",
    created_at="2026-09-12T15:42:36Z",
)


def _experiment(**over: object) -> BenchmarkExperiment:
    fields: dict[str, object] = {"id": uuid.uuid4(), **_BASE}
    fields.update(over)
    return BenchmarkExperiment(**fields)  # type: ignore[arg-type]


def test_benchmarks_endpoints_require_a_session(client: TestClient) -> None:
    assert client.get("/api/v1/soc/benchmarks").status_code == 401
    assert client.get(f"/api/v1/soc/benchmarks/{uuid.uuid4()}").status_code == 401


def test_list_benchmarks_requires_ops_read(client: TestClient, fixture, do_login) -> None:
    # analyst lacks ops:read (real seeded RBAC — only platform_operator has it)
    do_login("acme", fixture.acme_analyst.email)
    r = client.get("/api/v1/soc/benchmarks")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "permission_denied"


def test_list_benchmarks_allowed_for_operator(client: TestClient, fixture, do_login) -> None:
    exp = _experiment()
    fixture.services.benchmark_repository.experiments[exp.id] = exp
    do_login("acme", fixture.acme_admin.email)
    r = client.get("/api/v1/soc/benchmarks")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["dataset_id"] == "nsl-kdd"
    assert body[0]["metrics"]["roc_auc"] == 0.639039


def test_list_benchmarks_filters_by_dataset_id(client: TestClient, fixture, do_login) -> None:
    a = _experiment(dataset_id="nsl-kdd")
    b = _experiment(dataset_id="unsw-nb15")
    fixture.services.benchmark_repository.experiments[a.id] = a
    fixture.services.benchmark_repository.experiments[b.id] = b
    do_login("acme", fixture.acme_admin.email)
    r = client.get("/api/v1/soc/benchmarks", params={"dataset_id": "unsw-nb15"})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["dataset_id"] == "unsw-nb15"


def test_get_benchmark_by_id(client: TestClient, fixture, do_login) -> None:
    exp = _experiment()
    fixture.services.benchmark_repository.experiments[exp.id] = exp
    do_login("acme", fixture.acme_admin.email)
    r = client.get(f"/api/v1/soc/benchmarks/{exp.id}")
    assert r.status_code == 200
    assert r.json()["model_name"] == "mad_zscore"


def test_get_benchmark_404_when_missing(client: TestClient, fixture, do_login) -> None:
    do_login("acme", fixture.acme_admin.email)
    r = client.get(f"/api/v1/soc/benchmarks/{uuid.uuid4()}")
    assert r.status_code == 404
