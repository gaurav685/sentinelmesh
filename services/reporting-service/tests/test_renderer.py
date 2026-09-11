from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime

from pypdf import PdfReader

from sm_contracts import GroundedStatement, GroundingKind, Report, ReportTimelineEntry
from sm_reporting_service.renderer import render_pdf

_NOW = datetime.now(UTC)


def _text(pdf: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf))
    return "\n".join(page.extract_text() for page in reader.pages)


def _report(**over: object) -> Report:
    base: dict[str, object] = dict(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), created_at=_NOW, updated_at=_NOW,
        kind="incident", status="complete", subject_type="host", subject_id="web01",
        title="Test report", requested_by=uuid.uuid4(), generated_at=_NOW,
    )
    base.update(over)
    return Report(**base)  # type: ignore[arg-type]


def test_render_pdf_produces_a_pdf():
    pdf = render_pdf(_report())
    assert pdf.startswith(b"%PDF-")


def test_render_pdf_states_missing_sections_rather_than_omitting_them():
    report = _report(missing_sections=["affected_assets"])
    text = _text(render_pdf(report))
    assert "Missing" in text
    assert "affected_assets" in text


def test_render_pdf_prefixes_every_statement_with_its_grounding_tier():
    report = _report(findings=[
        GroundedStatement(text="Something inferred.", tier=GroundingKind.inference, ref="x"),
    ])
    text = _text(render_pdf(report))
    assert "INFERENCE" in text
    assert "Something inferred." in text


def test_render_pdf_handles_an_empty_report_without_raising():
    pdf = render_pdf(_report())
    assert pdf.startswith(b"%PDF-")
    assert _text(pdf)  # still a parseable PDF with at least the title/header


def test_render_pdf_includes_timeline_entries():
    report = _report(timeline=[
        ReportTimelineEntry(
            at=_NOW, kind="detection", title="Suspicious login", ref_id="d1",
            tier=GroundingKind.evidence,
        ),
    ])
    text = _text(render_pdf(report))
    assert "Timeline" in text
    assert "Suspicious login" in text
