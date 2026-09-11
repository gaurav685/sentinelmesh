"""PDF rendering — the architecture-approved report format this phase ships.

Renders exactly what `Report` carries and nothing else: a
`missing_sections` entry is stated as an omission, never silently dropped
or backfilled with invented content (Constitution §3). Every
`GroundedStatement` is prefixed with its tier in capitals (`EVIDENCE` /
`INFERENCE` / `PREDICTION` / `SYNTHETIC`) so a reader never has to guess
how sure the platform is about a given line.
"""

from __future__ import annotations

import io

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from sm_contracts import GroundedStatement, Report

__all__ = ["render_pdf"]


def _statement_line(s: GroundedStatement) -> str:
    ref = f" [{s.ref}]" if s.ref else ""
    return f"[{s.tier.value.upper()}] {s.text}{ref}"


def render_pdf(report: Report) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, title=report.title)
    styles = getSampleStyleSheet()
    story: list[object] = [
        Paragraph(report.title, styles["Title"]),
        Paragraph(
            f"Kind: {report.kind} | Status: {report.status} | "
            f"Subject: {report.subject_type.value}:{report.subject_id}",
            styles["Normal"],
        ),
        Spacer(1, 0.2 * inch),
    ]

    if report.missing_sections:
        story.append(Paragraph(
            "<b>Missing sections</b> (content dependency unreachable at generation "
            "time — never fabricated): " + ", ".join(report.missing_sections),
            styles["Normal"],
        ))
        story.append(Spacer(1, 0.15 * inch))

    if report.incident_metadata:
        story.append(Paragraph("Incident metadata", styles["Heading2"]))
        for k, v in report.incident_metadata.items():
            story.append(Paragraph(f"{k}: {v}", styles["Normal"]))
        story.append(Spacer(1, 0.1 * inch))

    if report.timeline:
        story.append(Paragraph("Timeline", styles["Heading2"]))
        for e in report.timeline:
            story.append(Paragraph(
                f"{e.at.isoformat()} - {e.title} ({e.kind}, ref {e.ref_id})", styles["Normal"]
            ))
        story.append(Spacer(1, 0.1 * inch))

    if report.affected_assets:
        story.append(Paragraph("Affected assets", styles["Heading2"]))
        for a in report.affected_assets:
            story.append(Paragraph(f"{a.subject_type.value}:{a.subject_id} ({a.role})", styles["Normal"]))
        story.append(Spacer(1, 0.1 * inch))

    if report.detection_ids:
        story.append(Paragraph("Detections", styles["Heading2"]))
        story.append(Paragraph(", ".join(report.detection_ids), styles["Normal"]))
        story.append(Spacer(1, 0.1 * inch))

    if report.technique_ids:
        story.append(Paragraph("ATT&CK mappings", styles["Heading2"]))
        story.append(Paragraph(", ".join(report.technique_ids), styles["Normal"]))
        story.append(Spacer(1, 0.1 * inch))

    if report.threat_score is not None:
        story.append(Paragraph(f"Threat score: {report.threat_score:.2f}", styles["Heading2"]))
        story.append(Spacer(1, 0.1 * inch))

    if report.evidence:
        story.append(Paragraph("Evidence", styles["Heading2"]))
        for s in report.evidence:
            story.append(Paragraph(_statement_line(s), styles["Normal"]))
        story.append(Spacer(1, 0.1 * inch))

    if report.findings:
        story.append(Paragraph("Analyst findings", styles["Heading2"]))
        for s in report.findings:
            story.append(Paragraph(_statement_line(s), styles["Normal"]))
        story.append(Spacer(1, 0.1 * inch))

    if report.recommendations:
        story.append(Paragraph("Recommendations", styles["Heading2"]))
        for s in report.recommendations:
            story.append(Paragraph(_statement_line(s), styles["Normal"]))
        story.append(Spacer(1, 0.1 * inch))

    if report.confidence is not None:
        story.append(Paragraph(f"Confidence: {report.confidence:.2f}", styles["Normal"]))

    if report.provenance:
        story.append(Paragraph("Provenance: " + ", ".join(report.provenance), styles["Normal"]))

    doc.build(story)
    return buf.getvalue()
