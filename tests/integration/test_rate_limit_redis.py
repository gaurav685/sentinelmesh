"""Rate-limit window semantics against a real Redis.

The unit tests use an in-memory counter, so the actual `INCR` + `EXPIRE`
behaviour and the one-minute TTL are only proven here.
"""

from __future__ import annotations

import time

import pytest
from sm_common.cache import Cache

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _flush(cache: Cache):
    await cache.client.flushdb()
    yield
    await cache.client.flushdb()


@pytest.mark.asyncio
async def test_incr_and_ttl(cache: Cache):
    window = int(time.time() // 60)
    key = cache.key("ratelimit", "203.0.113.5", str(window))

    assert await cache.client.incr(key) == 1
    await cache.client.expire(key, 65)
    assert await cache.client.incr(key) == 2

    ttl = await cache.client.ttl(key)
    assert 0 < ttl <= 65


@pytest.mark.asyncio
async def test_separate_ips_have_separate_counters(cache: Cache):
    window = str(int(time.time() // 60))
    a = cache.key("ratelimit", "10.0.0.1", window)
    b = cache.key("ratelimit", "10.0.0.2", window)

    for _ in range(5):
        await cache.client.incr(a)
    assert await cache.client.incr(b) == 1


@pytest.mark.asyncio
async def test_window_rolls_over(cache: Cache):
    now = int(time.time() // 60)
    this_window = cache.key("ratelimit", "10.0.0.9", str(now))
    next_window = cache.key("ratelimit", "10.0.0.9", str(now + 1))

    for _ in range(10):
        await cache.client.incr(this_window)

    # The next minute's bucket is a fresh key, so the count starts over.
    assert await cache.client.incr(next_window) == 1
