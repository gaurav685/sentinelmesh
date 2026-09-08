from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from sm_common.errors import PermissionDenied
from sm_common.fastapi import (
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    install_exception_handlers,
)


class Body(BaseModel):
    n: int


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    # Same registration order as the real services (add_middleware prepends, so
    # this makes RequestContext outermost and BodySizeLimit innermost).
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=64)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    install_exception_handlers(app)

    # raise_server_exceptions=False so we can assert on the canonical 500 body
    # instead of the exception bubbling out of the test client.
    @app.get("/ok")
    def _ok() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/boom")
    def _boom() -> None:
        raise PermissionDenied()

    @app.get("/crash")
    def _crash() -> None:
        raise RuntimeError("secret internal detail")

    @app.post("/echo")
    def _echo(b: Body) -> dict[str, int]:
        return {"n": b.n}

    return TestClient(app, raise_server_exceptions=False)


def test_request_id_echoed_and_valid_uuid(client: TestClient):
    r = client.get("/ok")
    assert r.status_code == 200
    UUID(r.headers["x-request-id"])  # parses


def test_client_request_id_preserved(client: TestClient):
    rid = "11111111-1111-1111-1111-111111111111"
    r = client.get("/ok", headers={"x-request-id": rid})
    assert r.headers["x-request-id"] == rid


def test_security_headers_present(client: TestClient):
    r = client.get("/ok")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_sm_error_canonical_shape(client: TestClient):
    r = client.get("/boom")
    assert r.status_code == 403
    body = r.json()
    assert body["error"]["code"] == "permission_denied"
    assert set(body["error"]) == {"code", "message", "request_id", "correlation_id", "details"}


def test_unexpected_error_is_masked(client: TestClient):
    r = client.get("/crash")
    assert r.status_code == 500
    assert "secret internal detail" not in r.text
    assert r.json()["error"]["code"] == "internal_error"


def test_validation_error_shape(client: TestClient):
    r = client.post("/echo", json={"n": "not-an-int"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert r.json()["error"]["details"]


def test_body_size_limit(client: TestClient):
    r = client.post("/echo", json={"n": 1, "pad": "x" * 200})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"


def test_body_limit_returns_canonical_413_with_a_real_request_id(client: TestClient):
    rid = "22222222-2222-2222-2222-222222222222"
    r = client.post("/echo", json={"n": 1, "pad": "x" * 200}, headers={"x-request-id": rid})
    assert r.status_code == 413
    body = r.json()["error"]
    assert body["code"] == "payload_too_large"
    # the id is the caller's, not a zeroed placeholder
    assert body["request_id"] == rid
    assert r.headers["x-content-type-options"] == "nosniff"
