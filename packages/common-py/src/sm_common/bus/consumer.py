"""Async Kafka consumer wrapper (ADR-008; event-model.md §4/§6).

`EventBusConsumer` wraps one `AIOKafkaConsumer` with the semantics every
SentinelMesh consumer needs:

- **manual commit after the side effect** — auto-commit is off; `run_once()`
  commits a poll batch's offsets only once every record has been handled (or
  dead-lettered). A crash mid-batch reprocesses the batch, so handlers must be
  idempotent on `event_id` (event-model.md §4).
- **at-least-once**, never exactly-once.
- **backpressure** — at most `max_records_per_poll` records in flight at once
  (`SM_KAFKA_MAX_POLL_RECORDS`); the loop does not fetch the next batch until the
  current one is committed.
- **graceful shutdown** — `request_stop()` lets the in-flight batch finish and
  commit; the lifespan then closes the client with `stop()` (bounded by
  `SM_KAFKA_SHUTDOWN_GRACE_MS`).
- **replay** — `seek_by_timestamp()` resets all assigned partitions to a wall
  time and reprocesses (event-model.md §6).
- **lag** — after each poll the per-partition distance from the high-watermark
  is exported as `sm_consumer_lag`.

The handler owns retry / DLQ policy for a *record* (`RecordProcessor` provides
the standard one). If the handler raises, `run_once()` does not commit and the
batch is redelivered — that path is for infrastructure failure, not poison data.
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
from ..observability import Metrics

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
        metrics: Metrics | None = None,
        service_name: str = "",
    ) -> None:
        self._topics = topics
        self.group_id = group_id
        self._max_records = max_records_per_poll
        self._metrics = metrics
        self._service = service_name
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
        self._batch_lock = asyncio.Lock()

    @classmethod
    def from_settings(
        cls,
        settings: AppSettings,
        *,
        topics: list[str],
        group_id: str | None = None,
        metrics: Metrics | None = None,
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
            max_records_per_poll=settings.kafka_max_poll_records,
            metrics=metrics,
            service_name=settings.service_name,
        )

    async def start(self) -> None:
        if not self._started:
            await self._consumer.start()
            self._started = True

    def request_stop(self) -> None:
        """Ask `run()` to exit after the in-flight batch commits. Does not close
        the client — call `stop()` after the run task has finished."""
        self._stopping = True

    async def stop(self) -> None:
        """Wait for any in-flight batch to release the lock, then close the
        client. Idempotent."""
        self._stopping = True
        if self._started:
            async with self._batch_lock:
                await self._consumer.stop()
                self._started = False

    async def ping(self) -> None:
        """Raises if no broker is reachable. Used by the readiness check."""
        await self._consumer.topics()

    async def seek_by_timestamp(self, when: datetime) -> dict[str, int]:
        """Replay: move every assigned partition to the first offset at/after
        `when` (event-model.md §6). Returns `{"<topic>-<partition>": offset}`."""
        assignment = self._consumer.assignment()
        if not assignment:
            await self._consumer.getmany(timeout_ms=1000)  # trigger assignment
            assignment = self._consumer.assignment()
        ms = int(when.timestamp() * 1000)
        offsets = await self._consumer.offsets_for_times({tp: ms for tp in assignment})
        moved: dict[str, int] = {}
        for tp, meta in offsets.items():
            target = meta.offset if meta is not None else (await self._consumer.end_offsets([tp]))[tp]
            self._consumer.seek(tp, target)
            moved[f"{tp.topic}-{tp.partition}"] = target
        _log.info("replay_seek", group=self.group_id, offsets=moved)
        return moved

    async def _sample_lag(self) -> None:
        if self._metrics is None:
            return
        for tp in self._consumer.assignment():
            highwater = self._consumer.highwater(tp)
            if highwater is None:
                continue
            try:
                position = await self._consumer.position(tp)
            except Exception:  # noqa: S112 - no position yet on this partition; skip this tick
                continue
            self._metrics.consumer_lag.labels(
                self._service, self.group_id, tp.topic, str(tp.partition)
            ).set(max(highwater - position, 0))

    async def run_once(self, handler: RecordHandler, *, timeout_ms: int = 1000) -> int:
        """Poll once, handle every record, commit, sample lag. Returns the count.

        On a handler exception the batch is **not committed and the fetch
        position is rewound** to the first record of the batch, so the very next
        poll of this same consumer redelivers it (aiokafka advances the in-memory
        fetch position on `getmany`; without the rewind a failed batch would only
        be redelivered after a rebalance or restart). At-least-once.
        """
        async with self._batch_lock:
            batches = await self._consumer.getmany(
                timeout_ms=timeout_ms, max_records=self._max_records
            )
            rewind = {tp: records[0].offset for tp, records in batches.items() if records}
            handled = 0
            try:
                for tp, records in batches.items():
                    for record in records:
                        await handler(record)
                        handled += 1
                    if self._metrics is not None and records:
                        self._metrics.consumer_records.labels(
                            self._service, self.group_id, tp.topic
                        ).inc(len(records))
            except BaseException:
                for tp, offset in rewind.items():
                    self._consumer.seek(tp, offset)
                raise
            if handled:
                await self._consumer.commit()
            await self._sample_lag()
            return handled

    async def run(self, handler: RecordHandler) -> None:
        """Consume until `request_stop()` / `stop()`. A stopped consumer stays
        stopped."""
        while not self._stopping:
            try:
                await self.run_once(handler)
            except Exception:
                _log.exception("consumer_batch_failed", group=self.group_id)
                # Do not spin hot on a persistent failure; the `while` check
                # picks up a concurrent stop on the next iteration.
                await asyncio.sleep(1.0)
