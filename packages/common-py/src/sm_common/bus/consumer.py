"""Async Kafka consumer wrapper (ADR-008; event-model.md §4).

`EventBusConsumer` wraps one `AIOKafkaConsumer` with the semantics every
SentinelMesh consumer needs:

- **manual commit after the side effect** — auto-commit is off; `run()` commits a
  batch's offsets only once every record in it has been handled (or dead-
  lettered). A crash mid-batch reprocesses the batch, so handlers must be
  idempotent on `event_id` (event-model.md §4).
- **at-least-once**, never exactly-once.
- one consumer group per logical consumer (`SM_KAFKA_CONSUMER_GROUP`).

The handler owns retry / DLQ policy for a *record*. If the handler raises, `run()`
does not commit and the batch is retried on the next poll — that path is for
infrastructure failure (the downstream broker or store is down), not poison
data, which the handler must DLQ itself.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime

import structlog
from aiokafka import AIOKafkaConsumer
from aiokafka.structs import ConsumerRecord

from ..clock import utcnow
from ..config import AppSettings

__all__ = ["EventBusConsumer", "dlq_payload"]

_log = structlog.get_logger("sm.bus.consumer")

RecordHandler = Callable[[ConsumerRecord], Awaitable[None]]

_MAX_DETAIL = 2000


def dlq_payload(
    *,
    original: bytes,
    error_type: str,
    error_detail: str,
    consumer_group: str,
    attempts: int,
    failed_at: datetime | None = None,
) -> bytes:
    """The canonical DLQ record shape (event-model.md §5): the original message
    plus why it failed. Used by every stream consumer's dead-letter path."""
    return json.dumps(
        {
            "original": original.decode("utf-8", "replace"),
            "error_type": error_type,
            "error_detail": error_detail[:_MAX_DETAIL],
            "consumer_group": consumer_group,
            "attempts": attempts,
            "failed_at": (failed_at or utcnow()).isoformat(),
        }
    ).encode("utf-8")


class EventBusConsumer:
    def __init__(
        self,
        *,
        topics: list[str],
        bootstrap_servers: str,
        group_id: str,
        client_id: str,
        security_protocol: str = "PLAINTEXT",
        sasl_mechanism: str | None = None,
        sasl_username: str | None = None,
        sasl_password: str | None = None,
        max_records_per_poll: int = 200,
    ) -> None:
        self._topics = topics
        self.group_id = group_id
        self._max_records = max_records_per_poll
        kwargs: dict[str, object] = {
            "bootstrap_servers": bootstrap_servers,
            "group_id": group_id,
            "client_id": client_id,
            "enable_auto_commit": False,
            "auto_offset_reset": "earliest",
            "security_protocol": security_protocol,
        }
        if security_protocol in ("SASL_PLAINTEXT", "SASL_SSL"):
            kwargs["sasl_mechanism"] = sasl_mechanism or "SCRAM-SHA-512"
            kwargs["sasl_plain_username"] = sasl_username or ""
            kwargs["sasl_plain_password"] = sasl_password or ""
        self._consumer = AIOKafkaConsumer(*topics, **kwargs)
        self._started = False
        self._stopping = False

    @classmethod
    def from_settings(
        cls, settings: AppSettings, *, topics: list[str], group_id: str | None = None
    ) -> EventBusConsumer:
        resolved_group = group_id or settings.kafka_consumer_group
        if not resolved_group:
            raise ValueError("SM_KAFKA_CONSUMER_GROUP is required for a consumer")
        return cls(
            topics=topics,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=resolved_group,
            client_id=settings.service_name,
            security_protocol=settings.kafka_security_protocol,
            sasl_username=(
                settings.kafka_sasl_username.get_secret_value()
                if settings.kafka_sasl_username
                else None
            ),
            sasl_password=(
                settings.kafka_sasl_password.get_secret_value()
                if settings.kafka_sasl_password
                else None
            ),
        )

    async def start(self) -> None:
        if not self._started:
            await self._consumer.start()
            self._started = True

    async def stop(self) -> None:
        self._stopping = True
        if self._started:
            await self._consumer.stop()
            self._started = False

    async def ping(self) -> None:
        """Raises if no broker is reachable. Used by the readiness check.
        `topics()` performs a metadata request against the cluster."""
        await self._consumer.topics()

    async def run_once(self, handler: RecordHandler, *, timeout_ms: int = 1000) -> int:
        """Poll once, handle every record, then commit. Returns the record count.

        A handler exception propagates **without** committing, so the batch is
        redelivered.
        """
        batches = await self._consumer.getmany(
            timeout_ms=timeout_ms, max_records=self._max_records
        )
        handled = 0
        for records in batches.values():
            for record in records:
                await handler(record)
                handled += 1
        if handled:
            await self._consumer.commit()
        return handled

    async def run(self, handler: RecordHandler) -> None:
        """Consume until `stop()` is called. A stopped consumer stays stopped."""
        while not self._stopping:
            try:
                await self.run_once(handler)
            except Exception:
                _log.exception("consumer_batch_failed", group=self.group_id)
                # Do not spin hot on a persistent failure; the `while` check
                # picks up a concurrent `stop()` on the next iteration.
                await asyncio.sleep(1.0)
