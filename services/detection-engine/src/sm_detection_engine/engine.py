"""Domain handler: one `events.canonical` record -> anomaly / detection / alert.

    telemetry -> features -> anomaly score -> evidence -> detection -> alert

Wrapped by `sm_common.bus.RecordProcessor`:
- unparseable / not an `event.canonical` envelope / a kind with no feature schema
  -> `PoisonError` (straight to the DLQ).
- a database write failure or a failed produce to `detections` -> `TransientError`.

No fictional conclusions: a detection is written only when a rule fired or the
composite score crossed the configured threshold, and every claim in it is an
`EvidenceItem` with a `provenance`.
"""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import UUID

import structlog
from aiokafka.structs import ConsumerRecord
from pydantic import ValidationError

from sm_common.bus import EventBusProducer, PoisonError, TransientError
from sm_common.clock import utcnow
from sm_common.config import AppSettings
from sm_common.context import get_correlation_id
from sm_common.ids import new_correlation_id
from sm_contracts import (
    CanonicalEventPayload,
    DetectionPayload,
    EventEnvelope,
    EventType,
    EvidenceItem,
    EvidenceKind,
    ScoringStatus,
    Severity,
    detection_dedup_key,
    detection_id_for,
    make_partition_key,
)
from sm_ml import FeatureVector, StatisticalModel, extract_features
from sm_ml.models import AnomalyScore

from .inference_client import InferenceClient
from .metrics import DetectionMetrics
from .repository import DetectionRepository
from .rules import RuleContext, RuleHit, primary_subject, run_rules
from .scoring import WEIGHTS_VERSION, composite_score, rule_component, severity_for
from .topics import DETECTIONS_TOPIC
from .version import PRODUCER
from .windows import EventTimeline, FeatureWindows

__all__ = ["DetectionEngine"]

_log = structlog.get_logger("sm.detection_engine.engine")
_ALERTING = {Severity.high, Severity.critical}
_DETECTING = {Severity.medium, Severity.high, Severity.critical}


class DetectionEngine:
    def __init__(
        self,
        *,
        settings: AppSettings,
        repository: DetectionRepository,
        producer: EventBusProducer,
        inference: InferenceClient,
        metrics: DetectionMetrics,
        windows: FeatureWindows | None = None,
        timeline: EventTimeline | None = None,
    ) -> None:
        self._cfg = settings
        self._repo = repository
        self._producer = producer
        self._inference = inference
        self._m = metrics
        self._windows = windows or FeatureWindows(size=settings.detection_window_size)
        self._timeline = timeline or EventTimeline(window_s=settings.detection_rule_window_s)

    async def handle(self, record: ConsumerRecord) -> None:
        start = time.perf_counter()
        envelope = _parse(record)
        canonical = envelope.payload
        tenant_id = envelope.tenant_id
        try:
            features = extract_features(canonical)
        except KeyError as exc:
            raise PoisonError(f"no feature schema for {canonical.kind.value}: {exc}") from exc

        self._m.event(canonical.kind.value)
        raw_event_id = str(canonical.raw_event_id)

        stat = await self._score_statistical(tenant_id, canonical, features, raw_event_id)
        self._windows.observe(tenant_id, canonical.kind, features.vector)
        model = await self._score_model(tenant_id, canonical, features, raw_event_id)

        ctx = RuleContext(
            tenant_id=tenant_id,
            timeline=self._timeline,
            now=canonical.occurred_at.timestamp(),
            raw_event_id=raw_event_id,
            rule_window_s=self._cfg.detection_rule_window_s,
        )
        hits = run_rules(canonical, features, ctx)
        for h in hits:
            self._m.rule_hit(h.rule_id)

        comp = composite_score(
            rule_value=rule_component([h.severity for h in hits]),
            statistical_normalized=stat.normalized_score if stat else None,
            model_normalized=model.normalized_score if model else None,
        )
        if comp.scoring_status is ScoringStatus.degraded and model is None:
            self._m.degrade("model_unavailable")

        rule_sevs = [h.severity for h in hits]
        severity = severity_for(comp.score, rule_sevs)
        should_detect = comp.score >= self._cfg.detection_score_threshold or severity in _DETECTING
        if should_detect:
            await self._raise_detection(envelope, canonical, features, hits, comp, severity, stat, model)

        self._m.duration.labels("detection-engine").observe(time.perf_counter() - start)

    # ---- anomaly scoring ------------------------------------------------
    async def _score_statistical(
        self, tenant_id: UUID, c: CanonicalEventPayload, fv: FeatureVector, raw_event_id: str
    ) -> AnomalyScore | None:
        sample = self._windows.sample(tenant_id, c.kind)
        if len(sample) < self._cfg.detection_min_samples:
            self._m.degrade("warming_up")
            return None
        model = StatisticalModel.fit(fv.names, sample, z_threshold=self._cfg.detection_anomaly_z)
        score = model.score(fv.vector)
        self._m.anomaly(score.method.value, score.is_anomaly)
        await self._persist_anomaly(tenant_id, c, fv, score)
        return score

    async def _score_model(
        self, tenant_id: UUID, c: CanonicalEventPayload, fv: FeatureVector, raw_event_id: str
    ) -> AnomalyScore | None:
        score = await self._inference.score(str(tenant_id), c.kind, fv.vector)
        if score is None:
            return None
        self._m.anomaly(score.method.value, score.is_anomaly)
        await self._persist_anomaly(tenant_id, c, fv, score)
        return score

    async def _persist_anomaly(
        self, tenant_id: UUID, c: CanonicalEventPayload, fv: FeatureVector, score: AnomalyScore
    ) -> None:
        try:
            await self._repo.add_anomaly(
                tenant_id=tenant_id, method=score.method.value,
                feature_schema_version=fv.schema_version, model_version=score.model_version,
                score=score.score, normalized_score=score.normalized_score, threshold=score.threshold,
                is_anomaly=score.is_anomaly,
                entity={"kind": c.actor.kind.value, "value": c.actor.value} if c.actor else None,
                raw_event_id=c.raw_event_id, observed_at=c.occurred_at, features=fv.values,
            )
        except Exception as exc:
            raise TransientError(f"anomaly write failed: {exc!r}") from exc

    # ---- detection ---------------------------------------------------
    async def _raise_detection(
        self,
        envelope: EventEnvelope[CanonicalEventPayload],
        c: CanonicalEventPayload,
        fv: FeatureVector,
        hits: list[RuleHit],
        comp: Any,
        severity: Severity,
        stat: AnomalyScore | None,
        model: AnomalyScore | None,
    ) -> None:
        tenant_id = envelope.tenant_id
        subject_type, subject_val = primary_subject(c)
        detector = "composite" if (stat or model) else "rule"
        rule_id = hits[0].rule_id if hits else None
        dedup_key = detection_dedup_key(tenant_id, detector, rule_id, subject_val)
        window = c.occurred_at.date().isoformat()
        detection_id = detection_id_for(dedup_key, window)

        evidence = _evidence(c, fv, hits, stat, model, str(c.raw_event_id))
        technique_ids = sorted({t for h in hits for t in h.technique_ids})
        title = hits[0].title if hits else f"Anomalous {c.kind.value} activity for {subject_val}"
        description = hits[0].description if hits else (
            f"The feature vector for this {c.kind.value} event is a statistical outlier "
            f"(composite score {comp.score:.2f})."
        )
        entities = [{"kind": e.kind.value, "value": e.value} for e in c.entities]

        try:
            await self._repo.upsert_detection(
                detection_id=detection_id, tenant_id=tenant_id, detector=detector, rule_id=rule_id,
                title=title, description=description, severity=severity.value, score=comp.score,
                scoring_status=comp.scoring_status.value, entities=entities,
                technique_ids=technique_ids,
                evidence=[e.model_dump(mode="json") for e in evidence],
                raw_event_id=c.raw_event_id, dedup_key=dedup_key, occurred_at=c.occurred_at,
            )
            await self._repo.upsert_threat_score(
                tenant_id=tenant_id, subject_type=subject_type.value, subject_id=subject_val,
                score=comp.score, components=comp.components, weights_version=WEIGHTS_VERSION,
                scoring_status=comp.scoring_status.value, computed_at=utcnow(),
            )
        except Exception as exc:
            raise TransientError(f"detection write failed: {exc!r}") from exc

        self._m.detection(detector, severity.value)

        alerted = severity in _ALERTING or comp.score >= self._cfg.detection_alert_threshold
        if alerted:
            try:
                created = await self._repo.ensure_alert(
                    detection_id=detection_id, tenant_id=tenant_id, severity=severity.value,
                    title=title, summary=description, opened_at=c.occurred_at,
                )
                self._m.alert("created" if created else "existing")
            except Exception as exc:
                self._m.alert_failure()
                raise TransientError(f"alert write failed: {exc!r}") from exc

        await self._emit(envelope, c, detection_id, detector, rule_id, severity, comp,
                         entities, technique_ids, dedup_key, len(evidence))

    async def _emit(
        self,
        source: EventEnvelope[CanonicalEventPayload],
        c: CanonicalEventPayload,
        detection_id: UUID,
        detector: str,
        rule_id: str | None,
        severity: Severity,
        comp: Any,
        entities: list[dict[str, str]],
        technique_ids: list[str],
        dedup_key: str,
        evidence_count: int,
    ) -> None:
        payload = DetectionPayload(
            detection_id=detection_id, tenant_id=source.tenant_id, occurred_at=c.occurred_at,
            detected_at=utcnow(), detector=detector, rule_id=rule_id, title=_short_title(c, rule_id),
            severity=severity, score=comp.score, scoring_status=comp.scoring_status,
            raw_event_id=c.raw_event_id,
            entities=c.entities, technique_ids=technique_ids,
            evidence_count=evidence_count, dedup_key=dedup_key,
        )
        env = EventEnvelope[DetectionPayload](
            event_id=detection_id, event_type=EventType.detection_raised, event_version=1,
            occurred_at=source.occurred_at, ingested_at=utcnow(), producer=PRODUCER,
            tenant_id=source.tenant_id, source=source.source,
            correlation_id=get_correlation_id() or source.correlation_id or new_correlation_id(),
            trace_id=source.trace_id,
            partition_key=make_partition_key(source.tenant_id, str(detection_id)),
            payload=payload, metadata={"raw_event_id": str(c.raw_event_id)},
        )
        try:
            await self._producer.send(
                DETECTIONS_TOPIC, key=env.partition_key, value=env.model_dump_json().encode("utf-8")
            )
        except Exception as exc:
            raise TransientError(f"produce to {DETECTIONS_TOPIC} failed: {exc!r}") from exc


def _short_title(c: CanonicalEventPayload, rule_id: str | None) -> str:
    subject = c.actor.value if c.actor else "unknown"
    return rule_id or f"anomalous {c.kind.value} for {subject}"


def _evidence(
    c: CanonicalEventPayload,
    fv: FeatureVector,
    hits: list[RuleHit],
    stat: AnomalyScore | None,
    model: AnomalyScore | None,
    raw_event_id: str,
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = [
        EvidenceItem(
            kind=EvidenceKind.event, ref=raw_event_id,
            summary=f"{c.kind.value} {c.action}"
            + (f" ({c.outcome})" if c.outcome else ""),
            detail={"actor": c.actor.value if c.actor else None,
                    "target": c.target.value if c.target else None},
            provenance=f"normalization-engine:{raw_event_id}",
        )
    ]
    for h in hits:
        items.extend(h.evidence)
    for score in (stat, model):
        if score is None:
            continue
        items.append(EvidenceItem(
            kind=EvidenceKind.anomaly_score,
            ref=f"{score.method.value}:{score.model_version or 'rolling-window'}",
            summary=f"{score.method.value} normalized score {score.normalized_score:.2f} "
                    f"(threshold {score.threshold:.2f}, {'anomalous' if score.is_anomaly else 'normal'})",
            detail={"score": score.score, "normalized_score": score.normalized_score,
                    "threshold": score.threshold,
                    "contributing_features": score.contributing_features},
            provenance=f"detection-engine:{raw_event_id}"
            if score.model_version is None else f"ml-inference:{score.model_version}",
        ))
    return items


def _parse(record: ConsumerRecord) -> EventEnvelope[CanonicalEventPayload]:
    raw = record.value if isinstance(record.value, bytes) else bytes(record.value or b"")
    try:
        doc: Any = json.loads(raw)
        if doc.get("event_type") != EventType.event_canonical.value:
            raise PoisonError(f"not an event.canonical record: {doc.get('event_type')!r}")
        return EventEnvelope[CanonicalEventPayload].model_validate(doc)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise PoisonError(f"unparseable events.canonical record: {exc!r}") from exc
    except ValidationError as exc:
        raise PoisonError(f"canonical envelope invalid: {exc}") from exc
