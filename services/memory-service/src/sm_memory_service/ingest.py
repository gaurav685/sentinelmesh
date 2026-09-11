"""Domain handler: one `attack_chains` update -> threat-memory upserts.

    attack_chains event -> full chain (correlation-engine) -> technique_ids
    -> pattern upsert + campaign match/attach + fingerprint upsert
    -> campaign.updates event

Wrapped by `sm_common.bus.RecordProcessor`: unparseable / not an
`attack_chain.updated` envelope -> `PoisonError` (DLQ); anything else
(dependency call, database write, produce) -> `TransientError` (retried,
then DLQ).
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from aiokafka.structs import ConsumerRecord
from pydantic import ValidationError

from sm_common.bus import EventBusProducer, PoisonError, TransientError
from sm_common.clock import utcnow
from sm_common.ids import new_correlation_id, uuid7
from sm_contracts import (
    AttackChainPayload,
    Campaign,
    CampaignUpdatePayload,
    EventEnvelope,
    EventType,
    make_partition_key,
)

from .chains_client import ChainsClient
from .metrics import MemoryMetrics
from .repository import MemoryRepository
from .topics import CAMPAIGN_UPDATES_TOPIC
from .version import PRODUCER

__all__ = ["MemoryIngestHandler"]

_log = structlog.get_logger("sm.memory_service.ingest")


class MemoryIngestHandler:
    def __init__(
        self, *, repo: MemoryRepository, chains: ChainsClient, producer: EventBusProducer,
        metrics: MemoryMetrics, campaign_similarity_threshold: float = 0.5,
    ) -> None:
        self._repo = repo
        self._chains = chains
        self._producer = producer
        self._m = metrics
        self._threshold = campaign_similarity_threshold

    async def handle(self, record: ConsumerRecord) -> None:
        envelope = _parse(record)
        payload = envelope.payload

        try:
            chain = await self._chains.get_chain(payload.tenant_id, payload.chain_id)
            if chain is None:
                _log.info("chain_not_found", chain_id=str(payload.chain_id))
                self._m.chain_skipped()
                return

            technique_ids = sorted(set(chain.technique_ids))
            if not technique_ids:
                self._m.chain_skipped()
                return

            await self._repo.upsert_pattern(
                chain.tenant_id, subject_type=chain.subject_type.value, subject_id=chain.subject_id,
                technique_ids=technique_ids, source=f"attack_chain:{chain.id}",
            )
            campaign = await self._repo.attach_chain_to_campaign(
                chain.tenant_id, chain_id=str(chain.id), technique_ids=technique_ids,
                threshold=self._threshold,
            )
            await self._repo.upsert_fingerprint(
                chain.tenant_id, subject_type=chain.subject_type.value, subject_id=chain.subject_id,
                technique_ids=technique_ids, campaign_id=str(campaign.id),
            )
            self._m.chain_ingested()
            await self._emit_campaign_update(envelope, campaign)
        except (PoisonError, TransientError):
            raise
        except Exception as exc:
            raise TransientError(f"memory ingest failed: {exc!r}") from exc

    async def _emit_campaign_update(
        self, source: EventEnvelope[AttackChainPayload], campaign: Campaign
    ) -> None:
        update = CampaignUpdatePayload(
            campaign_id=campaign.id, tenant_id=campaign.tenant_id, status=campaign.status,
            chain_count=len(campaign.chain_ids), technique_ids=campaign.technique_ids,
            first_seen=campaign.first_seen, last_seen=campaign.last_seen,
            updated_at=campaign.updated_at,
        )
        env = EventEnvelope[CampaignUpdatePayload](
            event_id=uuid7(), event_type=EventType.campaign_updated, event_version=1,
            occurred_at=utcnow(), ingested_at=utcnow(), producer=PRODUCER,
            tenant_id=campaign.tenant_id, source=source.source,
            correlation_id=source.correlation_id or new_correlation_id(),
            trace_id=source.trace_id,
            partition_key=make_partition_key(str(campaign.tenant_id), str(campaign.id)),
            payload=update, metadata={},
        )
        try:
            await self._producer.send(
                CAMPAIGN_UPDATES_TOPIC, key=env.partition_key, value=env.model_dump_json().encode("utf-8")
            )
        except Exception as exc:
            raise TransientError(f"produce to {CAMPAIGN_UPDATES_TOPIC} failed: {exc!r}") from exc
        self._m.campaign_update_emitted()


def _parse(record: ConsumerRecord) -> EventEnvelope[AttackChainPayload]:
    raw = record.value if isinstance(record.value, bytes) else bytes(record.value or b"")
    try:
        doc: Any = json.loads(raw)
        if doc.get("event_type") != EventType.attack_chain_updated.value:
            raise PoisonError(f"not an attack_chain.updated record: {doc.get('event_type')!r}")
        return EventEnvelope[AttackChainPayload].model_validate(doc)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise PoisonError(f"unparseable attack_chains record: {exc!r}") from exc
    except ValidationError as exc:
        raise PoisonError(f"attack_chains envelope invalid: {exc}") from exc
