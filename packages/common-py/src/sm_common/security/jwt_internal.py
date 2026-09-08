"""Internal service-to-service JWT (Engineering Constitution §5, ADR-016).

`api-gateway` mints a short-lived token per downstream call; the downstream
service verifies it. The token carries the authenticated user's identity and
tenant plus the target audience. It is **not** a user session token and never
reaches the browser.

Symmetric HS256 keyed by `SM_INTERNAL_JWT_SIGNING_KEY`. Production rotates the
key; `verify_internal_token` accepts a list of keys during rotation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID

import jwt

from ..clock import utcnow
from ..errors import Unauthenticated
from ..ids import uuid7

__all__ = ["InternalPrincipal", "mint_internal_token", "verify_internal_token"]

_ISSUER = "sentinelmesh-internal"
_ALG = "HS256"


@dataclass(frozen=True)
class InternalPrincipal:
    subject: str
    tenant_id: UUID
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    audience: str = ""
    jti: str = ""
    raw_claims: dict[str, object] = field(default_factory=dict)


def mint_internal_token(
    *,
    signing_key: str,
    subject: str,
    tenant_id: UUID,
    audience: str,
    roles: tuple[str, ...] = (),
    permissions: tuple[str, ...] = (),
    ttl_seconds: int = 300,
) -> str:
    if not signing_key:
        raise ValueError("signing_key must not be empty")
    now = utcnow()
    claims = {
        "iss": _ISSUER,
        "sub": subject,
        "aud": audience,
        "tenant_id": str(tenant_id),
        "roles": list(roles),
        "perms": list(permissions),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        "jti": str(uuid7()),
    }
    return jwt.encode(claims, signing_key, algorithm=_ALG)


def verify_internal_token(
    token: str,
    *,
    signing_keys: list[str],
    audience: str,
    leeway_seconds: int = 30,
) -> InternalPrincipal:
    last_err: Exception | None = None
    for key in signing_keys:
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[_ALG],
                audience=audience,
                issuer=_ISSUER,
                leeway=leeway_seconds,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
            return InternalPrincipal(
                subject=str(claims["sub"]),
                tenant_id=UUID(str(claims["tenant_id"])),
                roles=tuple(claims.get("roles", [])),
                permissions=tuple(claims.get("perms", [])),
                audience=str(claims["aud"]),
                jti=str(claims.get("jti", "")),
                raw_claims=claims,
            )
        except jwt.PyJWTError as exc:
            last_err = exc
    raise Unauthenticated("invalid internal token") from last_err
