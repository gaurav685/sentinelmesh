"""Report assembly: gather content from every named dependency
(service-catalog: `detection-engine`, `graph-service`, `mitre-service`,
`ai-analyst`, `memory-service`), render a PDF, upload it, persist the
result, and produce `report.generated`.

Grounding (Constitution §3): every `GroundedStatement` this module writes
carries the `GroundingKind` tier that actually produced it — `evidence` for
a real detection/pattern, `inference` for an ai-analyst-derived summary,
`prediction` for a memory-service forecast. A content dependency that is
unreachable lands its section name in `missing_sections` and the report as
a whole as `partial` — it never fabricates the missing content. Only an
object-storage failure (the PDF has nowhere to go) makes a report `failed`.
"""

from __future__ import annotations

from uuid import UUID

from sm_common.bus import EventBusProducer
from sm_common.clock import utcnow
from sm_common.context import get_correlation_id
from sm_common.errors import DependencyUnavailable
from sm_common.ids import new_correlation_id
from sm_common.objectstore import ObjectStore
from sm_contracts import (
    Detection,
    EventEnvelope,
    EventSource,
    EventType,
    GroundedStatement,
    GroundingKind,
    Report,
    ReportAsset,
    ReportGeneratedPayload,
    ReportKind,
    ReportStatus,
    ReportTimelineEntry,
    SourceType,
    ThreatSubjectType,
    make_partition_key,
)
from sm_contracts.api.prediction import Prediction

from .content_client import LABEL_SUBJECT_TYPE, SUBJECT_TYPE_LABEL, ContentClient
from .content_repository import ContentRepository
from .metrics import ReportMetrics
from .renderer import render_pdf
from .repository import ReportBody, ReportRepository
from .topics import REPORT_GENERATED_TOPIC
from .version import PRODUCER

__all__ = ["ReportGenerator"]


class ReportGenerator:
    def __init__(
        self, *, repo: ReportRepository, content_repo: ContentRepository, content: ContentClient,
        store: ObjectStore, producer: EventBusProducer, metrics: ReportMetrics, bucket: str,
    ) -> None:
        self._repo = repo
        self._content_repo = content_repo
        self._content = content
        self._store = store
        self._producer = producer
        self._metrics = metrics
        self._bucket = bucket

    async def generate(
        self, tenant_id: UUID, *, kind: ReportKind, subject_type: str, subject_id: str,
        title: str, requested_by: UUID,
    ) -> Report:
        started = utcnow()
        report = await self._repo.create_pending(
            tenant_id, kind=kind, subject_type=subject_type, subject_id=subject_id,
            title=title, requested_by=requested_by,
        )
        body = ReportBody()
        missing: list[str] = []
        body.incident_metadata = {"subject_type": subject_type, "subject_id": subject_id, "kind": kind}

        detections = await self._gather_detections(tenant_id, subject_type, subject_id, body)
        await self._gather_graph(tenant_id, subject_type, subject_id, body, missing)
        await self._gather_mitre(tenant_id, body, missing)
        await self._gather_memory(tenant_id, subject_type, subject_id, body, missing)
        await self._gather_ai_analyst(tenant_id, subject_type, subject_id, detections, body, missing)

        # A dependency this report's own template never asked for (e.g.
        # `executive_summary` has no `affected_assets` section) is not a
        # gap worth apologizing for.
        template_sections = set(await self._repo.template_sections(kind))
        if template_sections:
            missing = [m for m in missing if m in template_sections]

        status: ReportStatus = "partial" if missing else "complete"
        generated_at = utcnow()
        snapshot = Report(
            id=report.id, tenant_id=tenant_id, created_at=report.created_at, updated_at=report.updated_at,
            kind=kind, status=status, subject_type=ThreatSubjectType(subject_type), subject_id=subject_id,
            title=title, requested_by=requested_by, generated_at=generated_at,
            incident_metadata=body.incident_metadata, timeline=body.timeline,
            affected_assets=body.affected_assets, detection_ids=body.detection_ids,
            evidence=body.evidence, chain_ids=body.chain_ids, technique_ids=body.technique_ids,
            threat_score=body.threat_score, findings=body.findings,
            recommendations=body.recommendations, confidence=body.confidence,
            provenance=body.provenance, missing_sections=missing, storage_key=None,
        )

        storage_key: str | None = None
        try:
            pdf_bytes = render_pdf(snapshot)
            storage_key = await self._store.put_bytes(
                bucket=self._bucket, key_parts=(str(tenant_id), "reports", f"{report.id}.pdf"),
                body=pdf_bytes, content_type="application/pdf",
            )
        except DependencyUnavailable:
            status = "failed"
            self._metrics.content_dependency_unavailable("object-storage")

        saved = await self._repo.save_result(
            tenant_id, report.id, status=status, body=body, missing_sections=missing,
            storage_key=storage_key, generated_at=generated_at,
        )
        self._metrics.report_generated(kind=kind, status=status)
        self._metrics.observe_generation_seconds(
            kind=kind, seconds=(utcnow() - started).total_seconds()
        )
        if status != "failed":
            await self._emit_generated(saved)
        return saved

    # ---- detection-engine (direct SQL; see content_repository.py) -----
    async def _gather_detections(
        self, tenant_id: UUID, subject_type: str, subject_id: str, body: ReportBody,
    ) -> list[Detection]:
        if subject_type == "detection":
            det = await self._content_repo.get_detection(tenant_id, UUID(subject_id))
            detections = [det] if det is not None else []
        else:
            detections = await self._content_repo.list_detections_for_subject(
                tenant_id, subject_type=subject_type, subject_id=subject_id
            )
        for d in detections:
            body.detection_ids.append(str(d.id))
            body.technique_ids = sorted(set(body.technique_ids) | set(d.technique_ids))
            body.timeline.append(ReportTimelineEntry(
                at=d.first_seen, kind="detection", severity=d.severity, title=d.title,
                ref_id=str(d.id), tier=GroundingKind.evidence,
            ))
            body.evidence.append(GroundedStatement(
                text=f"Detection {d.title!r} (severity {d.severity.value}, score {d.score:.2f}).",
                tier=GroundingKind.evidence, ref=str(d.id),
            ))
        score = await self._content_repo.get_threat_score(
            tenant_id, subject_type=subject_type, subject_id=subject_id
        )
        if score is not None:
            body.threat_score = score.score
        body.provenance.append("detection-engine")
        return detections

    # ---- graph-service --------------------------------------------
    async def _gather_graph(
        self, tenant_id: UUID, subject_type: str, subject_id: str, body: ReportBody, missing: list[str],
    ) -> None:
        label = SUBJECT_TYPE_LABEL.get(subject_type)
        if label is None:
            missing.append("affected_assets")
            return
        try:
            neighborhood = await self._content.graph_neighbors(tenant_id, label=label, key=subject_id)
            if neighborhood:
                for node in neighborhood.get("nodes", []):
                    if str(node.get("id")) == subject_id:
                        continue
                    node_labels = node.get("labels") or []
                    asset_type = next(
                        (LABEL_SUBJECT_TYPE[lbl] for lbl in node_labels if lbl in LABEL_SUBJECT_TYPE), None
                    )
                    if asset_type is not None:
                        body.affected_assets.append(ReportAsset(
                            subject_type=ThreatSubjectType(asset_type), subject_id=str(node["id"]),
                            role="related",
                        ))
            body.provenance.append("graph-service")
        except DependencyUnavailable:
            missing.append("affected_assets")
            self._metrics.content_dependency_unavailable("graph-service")

    # ---- mitre-service ----------------------------------------------
    async def _gather_mitre(self, tenant_id: UUID, body: ReportBody, missing: list[str]) -> None:
        if not body.technique_ids:
            return
        try:
            techniques = await self._content.mitre_techniques(tenant_id)
            names = {t["technique_id"]: t["name"] for t in techniques if "technique_id" in t}
            described = [f"{tid} ({names.get(tid, 'unmapped')})" for tid in body.technique_ids]
            body.findings.append(GroundedStatement(
                text="ATT&CK techniques observed: " + ", ".join(described),
                tier=GroundingKind.evidence, ref="mitre-service",
            ))
            body.provenance.append("mitre-service")
        except DependencyUnavailable:
            missing.append("attack_mappings")
            self._metrics.content_dependency_unavailable("mitre-service")

    # ---- memory-service -----------------------------------------------
    async def _gather_memory(
        self, tenant_id: UUID, subject_type: str, subject_id: str, body: ReportBody, missing: list[str],
    ) -> None:
        try:
            patterns = await self._content.memory_patterns(
                tenant_id, subject_type=subject_type, subject_id=subject_id
            )
            for p in patterns:
                technique_count = len(p.get("technique_ids") or [])
                body.evidence.append(GroundedStatement(
                    text=(
                        f"Behavioral pattern of {technique_count} technique(s), "
                        f"observed {p.get('occurrence_count', 1)}x."
                    ),
                    tier=GroundingKind.evidence, ref=str(p.get("id")),
                ))
            raw = await self._content.predict_lateral_movement(
                tenant_id, subject_type=subject_type, subject_id=subject_id
            )
            if raw:
                prediction = Prediction.model_validate(raw)
                if prediction.confidence > 0.0:
                    body.findings.append(GroundedStatement(
                        text=(
                            f"Predicted lateral-movement target: {prediction.prediction} "
                            f"(confidence {prediction.confidence:.2f}, model {prediction.model_version})."
                        ),
                        tier=GroundingKind.prediction, ref="memory-service:predict:lateral_movement",
                    ))
            body.provenance.append("memory-service")
        except DependencyUnavailable:
            missing.append("evidence")
            self._metrics.content_dependency_unavailable("memory-service")

    # ---- ai-analyst (only when the subject IS a detection) --------------
    async def _gather_ai_analyst(
        self, tenant_id: UUID, subject_type: str, subject_id: str, detections: list[Detection],
        body: ReportBody, missing: list[str],
    ) -> None:
        if subject_type != "detection" or not detections:
            return
        try:
            evidence_refs = [
                {
                    "kind": "detection", "ref": str(d.id), "provenance": "detection-engine",
                    "content": f"{d.title}: {d.description or 'no description'}", "trusted": True,
                }
                for d in detections[:20]
            ]
            explanation = await self._content.explain(tenant_id, {
                "subject_type": "detection", "subject_id": subject_id,
                "task": "summarize", "evidence": evidence_refs,
            })
            if explanation:
                body.findings.append(GroundedStatement(
                    text=explanation["summary"], tier=GroundingKind.inference, ref="ai-analyst:explain",
                ))
                for rec in explanation.get("recommendations", []):
                    body.recommendations.append(GroundedStatement(
                        text=rec, tier=GroundingKind.inference, ref="ai-analyst:explain",
                    ))
                body.provenance.append("ai-analyst")
        except DependencyUnavailable:
            missing.append("findings")
            self._metrics.content_dependency_unavailable("ai-analyst")

    async def _emit_generated(self, report: Report) -> None:
        payload = ReportGeneratedPayload(
            report_id=report.id, tenant_id=report.tenant_id, kind=report.kind, status=report.status,
            subject_type=report.subject_type, subject_id=report.subject_id,
            generated_at=report.generated_at or utcnow(),
        )
        env = EventEnvelope[ReportGeneratedPayload](
            event_id=report.id, event_type=EventType.report_generated, event_version=1,
            occurred_at=utcnow(), ingested_at=utcnow(), producer=PRODUCER,
            tenant_id=report.tenant_id, source=EventSource(type=SourceType.internal),
            correlation_id=get_correlation_id() or new_correlation_id(),
            partition_key=make_partition_key(str(report.tenant_id), str(report.id)),
            payload=payload, metadata={},
        )
        await self._producer.send(
            REPORT_GENERATED_TOPIC, key=env.partition_key, value=env.model_dump_json().encode("utf-8")
        )
