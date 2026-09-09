"""Topic provisioning (ADR-008).

Partition counts and retention are **infrastructure**, not contract, but they
come *from* the contract registry (`sm_contracts.topics.TOPICS`) so the running
cluster and the catalog cannot drift.

`ensure_topics` is create-if-absent — safe to call on every startup / test run.
A real deployment pre-creates topics via IaC and never calls this in production;
it is for local Redpanda, CI, and the integration-test rig.
"""

from __future__ import annotations

import structlog
from aiokafka.admin import AIOKafkaAdminClient, NewPartitions, NewTopic
from aiokafka.errors import TopicAlreadyExistsError

from sm_contracts import TOPICS, TopicSpec, dlq_topic

from ..config import AppSettings

__all__ = ["ensure_topics"]

_log = structlog.get_logger("sm.bus.admin")


def _new_topics(specs: list[TopicSpec], *, replication: int) -> list[NewTopic]:
    out: list[NewTopic] = []
    for spec in specs:
        cfg: dict[str, str] = {"cleanup.policy": spec.cleanup}
        if spec.retention_ms is not None:
            cfg["retention.ms"] = str(spec.retention_ms)
        out.append(
            NewTopic(spec.name, num_partitions=spec.partitions,
                     replication_factor=replication, topic_configs=cfg)
        )
        if spec.has_dlq:
            out.append(
                NewTopic(dlq_topic(spec.name), num_partitions=spec.partitions,
                         replication_factor=replication,
                         topic_configs={"cleanup.policy": "delete",
                                        "retention.ms": str(30 * 86_400_000)})
            )
    return out


async def ensure_topics(
    settings: AppSettings,
    *,
    specs: list[TopicSpec] | None = None,
    replication: int = 1,
) -> list[str]:
    """Create every topic in `specs` (default: the whole catalog) plus its
    `.dlq`. A topic that already exists with **fewer** partitions than the spec
    is grown to match (Kafka allows increasing, never decreasing — the same rule
    as the catalog). Returns the names that were newly created."""
    targets = specs if specs is not None else list(TOPICS.values())

    kwargs: dict[str, object] = {
        "bootstrap_servers": settings.kafka_bootstrap_servers,
        "client_id": f"{settings.service_name}-admin",
        "security_protocol": settings.kafka_security_protocol,
    }
    if settings.kafka_security_protocol in ("SASL_PLAINTEXT", "SASL_SSL"):
        kwargs["sasl_mechanism"] = "SCRAM-SHA-512"
        kwargs["sasl_plain_username"] = (
            settings.kafka_sasl_username.get_secret_value() if settings.kafka_sasl_username else ""
        )
        kwargs["sasl_plain_password"] = (
            settings.kafka_sasl_password.get_secret_value() if settings.kafka_sasl_password else ""
        )

    wanted = _new_topics(targets, replication=replication)
    admin = AIOKafkaAdminClient(**kwargs)
    await admin.start()
    created: list[str] = []
    grown: list[str] = []
    try:
        for topic in wanted:
            try:
                await admin.create_topics([topic])
                created.append(topic.name)
            except TopicAlreadyExistsError:
                pass

        # Grow any topic that pre-exists with too few partitions (e.g. a broker
        # auto-created it at 1 during an earlier run).
        existing = {t.name for t in wanted} - set(created)
        if existing:
            described = await admin.describe_topics(list(existing))
            by_name = {d["topic"]: len(d["partitions"]) for d in described}
            want_partitions = {t.name: t.num_partitions for t in wanted}
            for name in existing:
                have = by_name.get(name, 0)
                want = want_partitions[name]
                if 0 < have < want:
                    await admin.create_partitions({name: NewPartitions(total_count=want)})
                    grown.append(f"{name}:{have}->{want}")
    finally:
        await admin.close()

    if created or grown:
        _log.info("topics_ensured", created=created, grown=grown)
    return created
