"""Repo-root ML tests share the ml-inference service's in-memory fixture rig.

The service directory name has a hyphen, so its conftest cannot be imported
as a package path; we load it via importlib and reuse its `build_settings`
and `write_statistical_artifact` helpers to build the same app the service's
own tests use.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

_ML_INF_CONFTEST = (
    Path(__file__).resolve().parents[2] / "services" / "ml-inference" / "tests" / "conftest.py"
)


def _load() -> Any:
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("ml_inference_test_conftest", _ML_INF_CONFTEST)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load ml-inference conftest from {_ML_INF_CONFTEST}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["ml_inference_test_conftest"] = module
    spec.loader.exec_module(module)
    return module


_C = _load()


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

    app = create_app(settings=_C.build_settings())
    with TestClient(app) as c:
        yield c


def auth(**kw: Any) -> dict[str, str]:
    return _C.auth(**kw)


def write_statistical_artifact(model_dir: Path, name: str, kind: Any) -> Any:
    return _C.write_statistical_artifact(model_dir, name, kind)