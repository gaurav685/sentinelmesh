"""Redis session and OIDC-state stores against a real Redis.

The unit tests use an in-memory session store, so the TTL semantics — sliding
idle window, hard absolute deadline, single-use OIDC state via `GETDEL` — are
only proven here.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from sm_api_gateway.security.session import RedisOidcStateStore, RedisSessionStore
from sm_common.cache import Cache

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _flush(cache: Cache):
    await cache.client.flushdb()
    yield
    await cache.client.flushdb()


@pytest.mark.asyncio
async def test_create_then_get_round_trips(cache: Cache):
    store = RedisSessionStore(cache, idle_seconds=60, absolute_seconds=300)
    user_id, tenant_id = uuid4(), uuid4()

    record = await store.create(user_id=user_id, tenant_id=tenant_id)
    loaded = await store.get(record.session_id)

    assert loaded is not None
    assert loaded.user_id == user_id
    assert loaded.tenant_id == tenant_id
    assert loaded.csrf_token == record.csrf_token


@pytest.mark.asyncio
async def test_session_is_namespaced_under_the_key_prefix(cache: Cache):
    store = RedisSessionStore(cache, idle_seconds=60, absolute_seconds=300)
    record = await store.create(user_id=uuid4(), tenant_id=uuid4())
    keys = [k async for k in cache.client.scan_iter(match="*session*")]
    assert any(record.session_id in k for k in keys)


@pytest.mark.asyncio
async def test_unknown_session_returns_none(cache: Cache):
    store = RedisSessionStore(cache, idle_seconds=60, absolute_seconds=300)
    assert await store.get("no-such-session") is None
    assert await store.get("") is None


@pytest.mark.asyncio
async def test_delete_removes_the_session(cache: Cache):
    store = RedisSessionStore(cache, idle_seconds=60, absolute_seconds=300)
    record = await store.create(user_id=uuid4(), tenant_id=uuid4())
    await store.delete(record.session_id)
    assert await store.get(record.session_id) is None


@pytest.mark.asyncio
async def test_idle_expiry_removes_the_session(cache: Cache):
    store = RedisSessionStore(cache, idle_seconds=1, absolute_seconds=300)
    record = await store.create(user_id=uuid4(), tenant_id=uuid4())
    await asyncio.sleep(1.4)
    assert await store.get(record.session_id) is None


@pytest.mark.asyncio
async def test_reading_refreshes_the_idle_window(cache: Cache):
    store = RedisSessionStore(cache, idle_seconds=2, absolute_seconds=300)
    record = await store.create(user_id=uuid4(), tenant_id=uuid4())

    # Two reads spaced under the idle timeout keep the session alive past the
    # point where it would have expired without the refresh.
    await asyncio.sleep(1.2)
    assert await store.get(record.session_id) is not None
    await asyncio.sleep(1.2)
    assert await store.get(record.session_id) is not None


@pytest.mark.asyncio
async def test_absolute_deadline_wins_over_the_idle_refresh(cache: Cache):
    """A session cannot be kept alive forever by touching it."""
    store = RedisSessionStore(cache, idle_seconds=60, absolute_seconds=1)
    record = await store.create(user_id=uuid4(), tenant_id=uuid4())
    await asyncio.sleep(1.2)

    assert await store.get(record.session_id) is None
    # and the record is gone, not merely reported as absent
    keys = [k async for k in cache.client.scan_iter(match="*session*")]
    assert all(record.session_id not in k for k in keys)


@pytest.mark.asyncio
async def test_malformed_record_is_dropped(cache: Cache):
    store = RedisSessionStore(cache, idle_seconds=60, absolute_seconds=300)
    key = cache.key("session", "corrupt")
    await cache.client.set(key, "not-json", ex=60)

    assert await store.get("corrupt") is None
    assert await cache.client.get(key) is None


@pytest.mark.asyncio
async def test_oidc_state_is_single_use(cache: Cache):
    store = RedisOidcStateStore(cache, ttl_seconds=60)
    flow = await store.create(
        tenant_id=uuid4(), nonce="n", code_verifier="v", redirect_uri="https://app/cb"
    )

    first = await store.consume(flow.state)
    assert first is not None
    assert first.nonce == "n"
    assert first.code_verifier == "v"

    # A replayed callback finds nothing.
    assert await store.consume(flow.state) is None


@pytest.mark.asyncio
async def test_oidc_state_expires(cache: Cache):
    store = RedisOidcStateStore(cache, ttl_seconds=1)
    flow = await store.create(
        tenant_id=uuid4(), nonce="n", code_verifier="v", redirect_uri="https://app/cb"
    )
    await asyncio.sleep(1.4)
    assert await store.consume(flow.state) is None


@pytest.mark.asyncio
async def test_unknown_oidc_state_returns_none(cache: Cache):
    store = RedisOidcStateStore(cache, ttl_seconds=60)
    assert await store.consume("never-issued") is None
    assert await store.consume("") is None
