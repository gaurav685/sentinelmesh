from __future__ import annotations

import base64
import hashlib
import time

import httpx
import jwt
import pytest
import respx

from sm_common.errors import DependencyUnavailable, Unauthenticated
from sm_common.security import OidcClient, make_pkce, new_state

ISSUER = "https://idp.example.com/realms/sentinelmesh"
DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
    "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
    "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
    "id_token_signing_alg_values_supported": ["HS256"],
}

SECRET = "hs256-shared-secret-for-tests-only-32b"


@pytest.fixture
def http() -> httpx.AsyncClient:
    return httpx.AsyncClient()


def _client(http: httpx.AsyncClient) -> OidcClient:
    return OidcClient(
        issuer=ISSUER, client_id="sm-api", client_secret="cs", audience="sm-api", http=http
    )


def test_pkce_s256():
    p = make_pkce()
    assert p.method == "S256"
    expected = base64.urlsafe_b64encode(hashlib.sha256(p.verifier.encode()).digest()).rstrip(b"=").decode()
    assert p.challenge == expected
    assert len(new_state()) >= 40


@respx.mock
@pytest.mark.asyncio
async def test_authorization_url(http: httpx.AsyncClient):
    respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(
        return_value=httpx.Response(200, json=DISCOVERY)
    )
    c = _client(http)
    url = await c.authorization_url(
        redirect_uri="https://app/cb", state="st", nonce="nn", pkce=make_pkce()
    )
    assert url.startswith(DISCOVERY["authorization_endpoint"])
    assert "code_challenge_method=S256" in url
    assert "state=st" in url and "nonce=nn" in url
    await http.aclose()


@respx.mock
@pytest.mark.asyncio
async def test_discovery_issuer_mismatch(http: httpx.AsyncClient):
    respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(
        return_value=httpx.Response(200, json={**DISCOVERY, "issuer": "https://evil"})
    )
    with pytest.raises(DependencyUnavailable):
        await _client(http)._discovery_doc()
    await http.aclose()


@respx.mock
@pytest.mark.asyncio
async def test_exchange_code_failure(http: httpx.AsyncClient):
    respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(
        return_value=httpx.Response(200, json=DISCOVERY)
    )
    respx.post(DISCOVERY["token_endpoint"]).mock(return_value=httpx.Response(400, json={"error": "x"}))
    with pytest.raises(Unauthenticated):
        await _client(http).exchange_code(code="c", redirect_uri="https://app/cb", code_verifier="v")
    await http.aclose()


@respx.mock
@pytest.mark.asyncio
async def test_verify_id_token_paths(http: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch):
    respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(
        return_value=httpx.Response(200, json=DISCOVERY)
    )
    c = _client(http)

    class _Key:
        key = SECRET

    async def _fake_key(_self: object, _tok: str) -> object:
        return _Key()

    monkeypatch.setattr(OidcClient, "_signing_key", _fake_key)

    now = int(time.time())
    good = jwt.encode(
        {"iss": ISSUER, "aud": "sm-api", "sub": "user-9", "email": "u@x.com",
         "iat": now, "exp": now + 300, "nonce": "nn"},
        SECRET, algorithm="HS256",
    )
    ident = await c.verify_id_token(good, expected_nonce="nn")
    assert ident.subject == "user-9"
    assert ident.email == "u@x.com"

    with pytest.raises(Unauthenticated):
        await c.verify_id_token(good, expected_nonce="different")

    bad_aud = jwt.encode(
        {"iss": ISSUER, "aud": "other", "sub": "x", "iat": now, "exp": now + 300},
        SECRET, algorithm="HS256",
    )
    with pytest.raises(Unauthenticated):
        await c.verify_id_token(bad_aud)

    await http.aclose()
