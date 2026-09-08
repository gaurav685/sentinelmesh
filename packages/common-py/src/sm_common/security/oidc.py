"""OIDC / OAuth2 authorization-code client (Engineering Constitution §5; ADR-016).

The `api-gateway` runs the auth-code flow with PKCE. This client:
- fetches and caches the provider discovery document
- builds the authorization-request URL (state + PKCE challenge + nonce)
- exchanges the code for tokens
- verifies the ID token (signature via JWKS, `iss`, `aud`, `exp`, `nonce`)

Secrets (`client_secret`) are never logged. No token is returned to the browser
by the gateway — this client only produces the verified identity.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import anyio
import httpx
import jwt

from ..config import AppSettings
from ..errors import DependencyUnavailable, Unauthenticated

__all__ = ["OidcClient", "OidcIdentity", "OidcTokens", "PkcePair", "make_pkce", "new_state"]


@dataclass(frozen=True)
class PkcePair:
    verifier: str
    challenge: str
    method: str = "S256"


@dataclass(frozen=True)
class OidcTokens:
    access_token: str
    id_token: str
    token_type: str = "Bearer"  # noqa: S105  (OAuth token_type value, not a credential)
    expires_in: int | None = None
    refresh_token: str | None = None
    scope: str | None = None


@dataclass(frozen=True)
class OidcIdentity:
    subject: str
    email: str | None = None
    email_verified: bool = False
    name: str | None = None
    claims: dict[str, Any] = field(default_factory=dict)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def make_pkce() -> PkcePair:
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return PkcePair(verifier=verifier, challenge=challenge)


def new_state() -> str:
    return _b64url(secrets.token_bytes(32))


class OidcClient:
    def __init__(
        self,
        *,
        issuer: str,
        client_id: str,
        client_secret: str,
        audience: str,
        http: httpx.AsyncClient,
        leeway_seconds: int = 30,
        discovery_ttl_s: int = 3600,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._audience = audience
        self._http = http
        self._leeway = leeway_seconds
        self._discovery_ttl = discovery_ttl_s
        self._discovery: dict[str, Any] | None = None
        self._discovery_at = 0.0
        self._jwk_client: jwt.PyJWKClient | None = None

    @classmethod
    def from_settings(cls, settings: AppSettings, http: httpx.AsyncClient) -> OidcClient:
        return cls(
            issuer=settings.oidc.issuer,
            client_id=settings.oidc.client_id,
            client_secret=settings.oidc_client_secret.get_secret_value(),
            audience=settings.oidc.audience,
            http=http,
            leeway_seconds=settings.oidc.leeway_seconds,
        )

    async def _discovery_doc(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._discovery is not None and (now - self._discovery_at) < self._discovery_ttl:
            return self._discovery
        url = f"{self._issuer}/.well-known/openid-configuration"
        try:
            resp = await self._http.get(url, timeout=10.0)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise DependencyUnavailable("OIDC provider discovery failed") from exc
        doc = resp.json()
        if not isinstance(doc, dict):
            raise DependencyUnavailable("OIDC discovery document is not an object")
        if str(doc.get("issuer", "")).rstrip("/") != self._issuer:
            raise DependencyUnavailable("OIDC discovery issuer mismatch")
        typed_doc: dict[str, Any] = doc
        self._discovery = typed_doc
        self._discovery_at = now
        self._jwk_client = None
        return typed_doc

    async def authorization_url(
        self, *, redirect_uri: str, state: str, nonce: str, pkce: PkcePair, scope: str = "openid email profile"
    ) -> str:
        doc = await self._discovery_doc()
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
            "nonce": nonce,
            "code_challenge": pkce.challenge,
            "code_challenge_method": pkce.method,
        }
        return f"{doc['authorization_endpoint']}?{urlencode(params)}"

    async def exchange_code(self, *, code: str, redirect_uri: str, code_verifier: str) -> OidcTokens:
        doc = await self._discovery_doc()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code_verifier": code_verifier,
        }
        try:
            resp = await self._http.post(doc["token_endpoint"], data=data, timeout=10.0)
        except httpx.HTTPError as exc:
            raise DependencyUnavailable("OIDC token endpoint unreachable") from exc
        if resp.status_code != 200:
            raise Unauthenticated("authorization code exchange failed")
        body = resp.json()
        if "id_token" not in body or "access_token" not in body:
            raise Unauthenticated("token response missing id_token/access_token")
        return OidcTokens(
            access_token=body["access_token"],
            id_token=body["id_token"],
            token_type=body.get("token_type", "Bearer"),
            expires_in=body.get("expires_in"),
            refresh_token=body.get("refresh_token"),
            scope=body.get("scope"),
        )

    async def _signing_key(self, id_token: str) -> jwt.PyJWK:
        doc = await self._discovery_doc()
        if self._jwk_client is None:
            self._jwk_client = jwt.PyJWKClient(doc["jwks_uri"])
        client = self._jwk_client
        return await anyio.to_thread.run_sync(client.get_signing_key_from_jwt, id_token)

    async def verify_id_token(self, id_token: str, *, expected_nonce: str | None = None) -> OidcIdentity:
        doc = await self._discovery_doc()
        try:
            key = await self._signing_key(id_token)
            claims = jwt.decode(
                id_token,
                key.key,
                algorithms=doc.get("id_token_signing_alg_values_supported", ["RS256"]),
                audience=self._client_id,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise Unauthenticated("invalid ID token") from exc
        if expected_nonce is not None and claims.get("nonce") != expected_nonce:
            raise Unauthenticated("ID token nonce mismatch")
        return OidcIdentity(
            subject=str(claims["sub"]),
            email=claims.get("email"),
            email_verified=bool(claims.get("email_verified", False)),
            name=claims.get("name"),
            claims=claims,
        )
