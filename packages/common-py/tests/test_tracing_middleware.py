from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from sm_common.fastapi import RequestContextMiddleware, TracingMiddleware


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(TracingMiddleware)

    @app.get("/ok")
    def _ok() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app)


def test_request_still_reaches_the_handler_unchanged() -> None:
    r = _client().get("/ok")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_no_traceparent_header_is_fabricated_with_no_real_provider_configured() -> None:
    # This is the ubiquitous local-dev/CI case (ADR-020): no OTel provider is
    # installed, so the span the middleware opens is a no-op with an invalid
    # context. The W3C propagator injects nothing for an invalid context —
    # exactly right, since a fabricated header would be a fake trace id.
    r = _client().get("/ok")
    assert "traceparent" not in r.headers


def test_an_inbound_traceparent_does_not_break_the_request() -> None:
    r = _client().get(
        "/ok",
        headers={"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"},
    )
    assert r.status_code == 200
