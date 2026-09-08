"""Async Redis client (Engineering Constitution §9, §15; ADR-009).

Redis here is cache / session / rate-limit / short-lived state — never the
durable event bus. `Cache` wraps a client plus the configured key prefix so
callers build namespaced keys consistently (`cache.key("session", sid)`).
"""

from __future__ import annotations

from typing import cast

import redis.asyncio as aioredis

from ..config import AppSettings

__all__ = ["Cache", "build_redis"]


def build_redis(settings: AppSettings) -> aioredis.Redis:
    password = settings.redis_password.get_secret_value() if settings.redis_password else None
    client = aioredis.Redis.from_url(
        settings.redis_url,
        password=password,
        decode_responses=True,
        socket_timeout=3.0,
        socket_connect_timeout=3.0,
        health_check_interval=30,
    )
    return cast("aioredis.Redis", client)


class Cache:
    def __init__(self, client: aioredis.Redis, *, key_prefix: str = "sm") -> None:
        self._client = client
        self._prefix = key_prefix

    @classmethod
    def from_settings(cls, settings: AppSettings) -> Cache:
        return cls(build_redis(settings), key_prefix=settings.redis_key_prefix)

    @property
    def client(self) -> aioredis.Redis:
        return self._client

    def key(self, *parts: str) -> str:
        return ":".join((self._prefix, *parts))

    async def ping(self) -> None:
        """Raises if Redis is unreachable. Used by the readiness check."""
        await self._client.ping()

    async def close(self) -> None:
        await self._client.aclose()
