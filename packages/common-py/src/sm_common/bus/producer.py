"""Async Kafka producer wrapper (ADR-008; event-model.md).

`EventBusProducer` wraps one `AIOKafkaProducer` configured the way every
SentinelMesh producer needs it:

- **idempotent** (`enable_idempotence=True`) so a producer-side retry cannot
  duplicate a record on a partition; this forces `acks=all`.
- bounded retries and a send timeout, so a broker outage surfaces as an error
  the caller can turn into `503` rather than hanging the request.
- keyed sends: the caller passes the envelope's `partition_key` as the record
  key, so all events for one entity land on one partition and stay ordered.

`start()` / `stop()` are driven by the service lifespan. `ping()` backs the
readiness probe: it forces a metadata refresh, which fails if no broker is
reachable.
"""

from __future__ import annotations

from types import TracebackType

from aiokafka import AIOKafkaProducer

from ..config import AppSettings
from ..observability import Metrics

__all__ = ["EventBusProducer"]

Headers = list[tuple[str, bytes]]


class EventBusProducer:
    def __init__(
        self,
        *,
        bootstrap_servers: str,
        client_id: str,
        security_protocol: str = "PLAINTEXT",
        sasl_mechanism: str | None = None,
        sasl_username: str | None = None,
        sasl_password: str | None = None,
        send_timeout_ms: int = 10_000,
        linger_ms: int = 5,
        metrics: Metrics | None = None,
        service_name: str = "",
    ) -> None:
        self._send_timeout_ms = send_timeout_ms
        self._metrics = metrics
        self._service = service_name
        kwargs: dict[str, object] = {
            "bootstrap_servers": bootstrap_servers,
            "client_id": client_id,
            "enable_idempotence": True,  # implies acks="all"
            "request_timeout_ms": send_timeout_ms,
            "linger_ms": linger_ms,
            "security_protocol": security_protocol,
        }
        if security_protocol in ("SASL_PLAINTEXT", "SASL_SSL"):
            kwargs["sasl_mechanism"] = sasl_mechanism or "SCRAM-SHA-512"
            kwargs["sasl_plain_username"] = sasl_username or ""
            kwargs["sasl_plain_password"] = sasl_password or ""
        self._producer = AIOKafkaProducer(**kwargs)
        self._started = False

    @classmethod
    def from_settings(
        cls, settings: AppSettings, *, metrics: Metrics | None = None
    ) -> EventBusProducer:
        return cls(
            bootstrap_servers=settings.kafka_bootstrap_servers,
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
            send_timeout_ms=settings.kafka_send_timeout_ms,
            linger_ms=settings.kafka_linger_ms,
            metrics=metrics,
            service_name=settings.service_name,
        )

    async def start(self) -> None:
        if not self._started:
            await self._producer.start()
            self._started = True

    async def stop(self) -> None:
        """Flush buffered records, then close. `AIOKafkaProducer.stop()` already
        flushes, but the explicit call makes the intent (no lost buffered sends
        on a clean shutdown) obvious and independent of that guarantee."""
        if self._started:
            await self._producer.flush()
        await self._producer.stop()  # idempotent; also closes a never-started client
        self._started = False

    async def send(
        self, topic: str, *, key: str, value: bytes, headers: Headers | None = None
    ) -> None:
        """Send one record and wait for the broker acknowledgement. Raises on any
        produce error (no broker, timeout, not-acked) — the caller decides what a
        failure means for the request."""
        try:
            if not self._started:
                raise RuntimeError("event bus producer is not started")
            await self._producer.send_and_wait(
                topic, value=value, key=key.encode("utf-8"), headers=headers or []
            )
        except Exception:
            if self._metrics is not None:
                self._metrics.producer_send_errors.labels(self._service, topic).inc()
            raise

    async def ping(self) -> None:
        """Raises if no broker is reachable. Used by the readiness check."""
        await self._producer.client.force_metadata_update()

    async def __aenter__(self) -> EventBusProducer:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.stop()
