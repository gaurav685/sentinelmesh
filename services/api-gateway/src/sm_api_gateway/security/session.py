"""Server-side session store and the OIDC flow-state store (ADR-016).

The browser holds only an opaque session id in an httpOnly cookie. Everything
authoritative — which user, which tenant — lives server-side in Redis. Roles and
permissions are deliberately **not** stored in the session: they are re-resolved
from the database on every request, so a revoked role takes effect immediately
and a stolen cookie cannot carry stale privileges.

Two expiries apply: a sliding idle timeout (the Redis TTL, refreshed on each
read) and a hard absolute deadline stored inside the record.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from sm_common.cache import Cache
from sm_common.clock import utcnow

__all__ = [
    "OidcFlowState",
    "OidcStateStore",
    "RedisOidcStateStore",
    "RedisSessionStore",
    "SessionRecord",
    "SessionStore",
]


def _token() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    user_id: UUID
    tenant_id: UUID
    csrf_token: str
    created_at: datetime
    absolute_expires_at: datetime


class SessionStore(Protocol):
    async def create(self, *, user_id: UUID, tenant_id: UUID) -> SessionRecord: ...

    async def get(self, session_id: str) -> SessionRecord | None: ...

    async def delete(self, session_id: str) -> None: ...


class RedisSessionStore:
    def __init__(self, cache: Cache, *, idle_seconds: int, absolute_seconds: int) -> None:
        self._cache = cache
        self._idle = idle_seconds
        self._absolute = absolute_seconds

    def _key(self, session_id: str) -> str:
        return self._cache.key("session", session_id)

    async def create(self, *, user_id: UUID, tenant_id: UUID) -> SessionRecord:
        now = utcnow()
        record = SessionRecord(
            session_id=_token(),
            user_id=user_id,
            tenant_id=tenant_id,
            csrf_token=_token(),
            created_at=now,
            absolute_expires_at=now + timedelta(seconds=self._absolute),
        )
        payload = json.dumps(
            {
                "user_id": str(record.user_id),
                "tenant_id": str(record.tenant_id),
                "csrf_token": record.csrf_token,
                "created_at": record.created_at.isoformat(),
                "absolute_expires_at": record.absolute_expires_at.isoformat(),
            }
        )
        await self._cache.client.set(self._key(record.session_id), payload, ex=self._idle)
        return record

    async def get(self, session_id: str) -> SessionRecord | None:
        if not session_id:
            return None
        key = self._key(session_id)
        raw = await self._cache.client.get(key)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            record = SessionRecord(
                session_id=session_id,
                user_id=UUID(data["user_id"]),
                tenant_id=UUID(data["tenant_id"]),
                csrf_token=data["csrf_token"],
                created_at=datetime.fromisoformat(data["created_at"]),
                absolute_expires_at=datetime.fromisoformat(data["absolute_expires_at"]),
            )
        except (ValueError, KeyError, TypeError):
            # A malformed record is treated as no session, and removed.
            await self._cache.client.delete(key)
            return None

        if utcnow() >= record.absolute_expires_at:
            await self._cache.client.delete(key)
            return None

        # Sliding idle window.
        await self._cache.client.expire(key, self._idle)
        return record

    async def delete(self, session_id: str) -> None:
        if session_id:
            await self._cache.client.delete(self._key(session_id))


@dataclass(frozen=True)
class OidcFlowState:
    state: str
    tenant_id: UUID
    nonce: str
    code_verifier: str
    redirect_uri: str


class OidcStateStore(Protocol):
    async def create(
        self, *, tenant_id: UUID, nonce: str, code_verifier: str, redirect_uri: str
    ) -> OidcFlowState: ...

    async def consume(self, state: str) -> OidcFlowState | None:
        """Single-use: a state value is valid for exactly one callback."""
        ...


class RedisOidcStateStore:
    def __init__(self, cache: Cache, *, ttl_seconds: int) -> None:
        self._cache = cache
        self._ttl = ttl_seconds

    def _key(self, state: str) -> str:
        return self._cache.key("oidc_state", state)

    async def create(
        self, *, tenant_id: UUID, nonce: str, code_verifier: str, redirect_uri: str
    ) -> OidcFlowState:
        flow = OidcFlowState(
            state=_token(),
            tenant_id=tenant_id,
            nonce=nonce,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
        payload = json.dumps(
            {
                "tenant_id": str(flow.tenant_id),
                "nonce": flow.nonce,
                "code_verifier": flow.code_verifier,
                "redirect_uri": flow.redirect_uri,
            }
        )
        await self._cache.client.set(self._key(flow.state), payload, ex=self._ttl)
        return flow

    async def consume(self, state: str) -> OidcFlowState | None:
        if not state:
            return None
        key = self._key(state)
        raw = await self._cache.client.getdel(key)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return OidcFlowState(
                state=state,
                tenant_id=UUID(data["tenant_id"]),
                nonce=data["nonce"],
                code_verifier=data["code_verifier"],
                redirect_uri=data["redirect_uri"],
            )
        except (ValueError, KeyError, TypeError):
            return None
