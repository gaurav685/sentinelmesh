from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from sm_common.audit import GENESIS_HASH, AuditWriter, verify_chain
from sm_common.db.models import AuditLog
from sm_contracts import ActorType, AuditResult


class _Result:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        return self._value


class FakeSession:
    """Minimal AsyncSession stand-in: records SQL, serves a canned last hash.

    Real Postgres behaviour (advisory lock, FOR-UPDATE ordering, constraints) is
    covered by the integration tests, which need Docker.
    """

    def __init__(self, last_hash: str | None = None) -> None:
        self.last_hash = last_hash
        self.statements: list[str] = []
        self.added: list[Any] = []
        self.flushed = 0

    async def execute(self, stmt: object, params: dict[str, Any] | None = None) -> _Result:
        self.statements.append(str(stmt))
        if "pg_advisory_xact_lock" in str(stmt):
            return _Result(None)
        return _Result(self.last_hash)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed += 1


def _kwargs(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tenant_id": uuid4(),
        "actor_type": ActorType.user.value,
        "actor_id": uuid4(),
        "action": "auth.login",
        "resource_type": "user",
        "resource_id": "u-1",
        "result": AuditResult.success.value,
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_first_entry_uses_genesis_prev_hash():
    session = FakeSession(last_hash=None)
    entry = await AuditWriter().append(session, **_kwargs())  # type: ignore[arg-type]
    assert entry.prev_hash == GENESIS_HASH
    assert len(entry.hash) == 64
    assert session.flushed == 1
    assert session.added == [entry]


@pytest.mark.asyncio
async def test_advisory_lock_taken_before_reading_last_hash():
    session = FakeSession(last_hash=None)
    await AuditWriter().append(session, **_kwargs())  # type: ignore[arg-type]
    assert "pg_advisory_xact_lock" in session.statements[0]
    assert "audit_log" in session.statements[1]


@pytest.mark.asyncio
async def test_second_entry_chains_from_stored_hash():
    writer = AuditWriter()
    first = await writer.append(FakeSession(last_hash=None), **_kwargs())  # type: ignore[arg-type]
    second = await writer.append(FakeSession(last_hash=first.hash), **_kwargs(action="auth.logout"))  # type: ignore[arg-type]
    assert second.prev_hash == first.hash
    assert second.hash != first.hash


@pytest.mark.asyncio
async def test_hash_payload_verifies_as_a_chain():
    writer = AuditWriter()
    entries: list[AuditLog] = []
    last: str | None = None
    tenant = uuid4()
    for i in range(4):
        e = await writer.append(  # type: ignore[arg-type]
            FakeSession(last_hash=last), **_kwargs(tenant_id=tenant, action=f"act.{i}")
        )
        entries.append(e)
        last = e.hash
    chain = [(e.hash, AuditWriter.hash_payload(e)) for e in entries]
    assert verify_chain(chain) is True


@pytest.mark.asyncio
async def test_tamper_breaks_verification():
    writer = AuditWriter()
    e = await writer.append(FakeSession(last_hash=None), **_kwargs())  # type: ignore[arg-type]
    payload = AuditWriter.hash_payload(e)
    payload["result"] = AuditResult.failure.value
    assert verify_chain([(e.hash, payload)]) is False


@pytest.mark.asyncio
async def test_platform_entry_uses_platform_lock_key():
    session = FakeSession(last_hash=None)
    entry = await AuditWriter().append(  # type: ignore[arg-type]
        session, **_kwargs(tenant_id=None, actor_type=ActorType.system.value, actor_id=None)
    )
    assert entry.tenant_id is None
    assert entry.prev_hash == GENESIS_HASH
