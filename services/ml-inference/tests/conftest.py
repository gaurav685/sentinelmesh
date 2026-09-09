from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from sm_common.config import AppSettings
from sm_common.security import mint_internal_token
from sm_contracts import CanonicalKind
from sm_ml import StatisticalModel, schema_for

_TEST_JWT_KEY = "ml-inference-test-signing-key-0123456789"


def build_settings(**over: Any) -> AppSettings:
    values: dict[str, Any] = {
        "service_name": "ml-inference",
        "pg_password": "x",
        "internal_jwt_signing_key": _TEST_JWT_KEY,
        "oidc_client_secret": "s",
        "neo4j_password": "x",
    }
    values.update(over)
    return AppSettings(_env_file=None, **values)


def internal_token(*, key: str = _TEST_JWT_KEY, audience: str = "ml-inference") -> str:
    import uuid

    return mint_internal_token(
        signing_key=key, subject="detection-engine", tenant_id=uuid.uuid4(), audience=audience
    )


def auth(**kw: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {internal_token(**kw)}"}


def write_statistical_artifact(model_dir: Path, name: str, kind: CanonicalKind) -> StatisticalModel:
    names = schema_for(kind).names
    rows = [[float((i + j) % 5) for j in range(len(names))] for i in range(50)]
    model = StatisticalModel.fit(names, rows, z_threshold=3.5)
    vdir = model_dir / name / "0.1.0"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "model.json").write_text(json.dumps(model.to_dict()), encoding="utf-8")
    (vdir / "metadata.json").write_text(
        json.dumps({
            "model_version": "0.1.0", "method": "mad_zscore", "task": "anomaly_score",
            "feature_schema_version": schema_for(kind).version,
        }),
        encoding="utf-8",
    )
    return model


@pytest.fixture
def model_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "artifacts"
    d.mkdir()
    monkeypatch.setenv("SM_ML_MODEL_DIR", str(d))
    return d


@pytest.fixture
def client(model_dir: Path) -> Iterator[Any]:
    from fastapi.testclient import TestClient
    from sm_ml_inference.app import create_app

    app = create_app(settings=build_settings())
    with TestClient(app) as c:
        yield c
