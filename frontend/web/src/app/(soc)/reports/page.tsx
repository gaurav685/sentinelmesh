"use client";

import { type FormEvent, useState } from "react";
import type { GroundedStatement, Report, ReportDownload } from "@sentinelmesh/contracts";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { EmptyState, ErrorState, Loading } from "@/components/states";
import { GroundingTag } from "@/components/GroundingTag";

type Async<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; error: Error }
  | { status: "done"; data: T };

const KINDS = ["incident", "executive_summary", "soc", "compliance"] as const;
const SUBJECT_TYPES = ["identity", "host", "ip", "domain", "detection"] as const;

export default function ReportsPage() {
  const { csrfToken } = useAuth();
  const [library, setLibrary] = useState<Report[]>([]);

  return (
    <div className="grid">
      <div className="page-head">
        <h1>Reports</h1>
      </div>
      <p className="state__hint">
        Every finding, recommendation, and timeline point below is tagged with how it is
        grounded — evidence, inference, prediction, or synthetic (simulation-sourced). A
        content dependency that is unreachable at generation time is listed under &ldquo;missing
        sections&rdquo; rather than invented.
      </p>

      <BuilderPanel csrfToken={csrfToken} onGenerated={(r) => setLibrary((l) => [r, ...l])} />
      <LibraryPanel reports={library} />
      <LookupPanel />
    </div>
  );
}

function BuilderPanel({
  csrfToken,
  onGenerated,
}: {
  csrfToken: string | null;
  onGenerated: (r: Report) => void;
}) {
  const [kind, setKind] = useState<(typeof KINDS)[number]>("incident");
  const [subjectType, setSubjectType] = useState<(typeof SUBJECT_TYPES)[number]>("host");
  const [subjectId, setSubjectId] = useState("");
  const [title, setTitle] = useState("");
  const [result, setResult] = useState<Async<Report>>({ status: "idle" });

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!subjectId.trim() || !title.trim()) return;
    setResult({ status: "loading" });
    try {
      const data = await api.createReport(
        { kind, subject_type: subjectType, subject_id: subjectId.trim(), title: title.trim() },
        csrfToken,
      );
      setResult({ status: "done", data });
      onGenerated(data);
    } catch (e) {
      setResult({ status: "error", error: e instanceof Error ? e : new Error(String(e)) });
    }
  }

  return (
    <>
      <div className="panel">
        <h2>Generate a report</h2>
        <form onSubmit={onSubmit} style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label className="field">
            <span>Kind</span>
            <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Subject type</span>
            <select value={subjectType} onChange={(e) => setSubjectType(e.target.value as typeof subjectType)}>
              {SUBJECT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label className="field" style={{ minWidth: 200 }}>
            <span>Subject id</span>
            <input value={subjectId} onChange={(e) => setSubjectId(e.target.value)} placeholder="web01" />
          </label>
          <label className="field" style={{ minWidth: 240 }}>
            <span>Title</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Host incident" />
          </label>
          <button type="submit" className="btn">
            Generate
          </button>
        </form>
        {kind === "compliance" ? (
          <p className="state__hint">Compliance reports require the lead or tenant_admin role.</p>
        ) : null}
      </div>

      {result.status === "loading" ? <Loading label="Generating report…" /> : null}
      {result.status === "error" ? <ErrorState error={result.error} /> : null}
      {result.status === "done" ? <ReportSummary report={result.data} /> : null}
    </>
  );
}

function ReportSummary({ report }: { report: Report }) {
  return (
    <div className="panel">
      <h2>
        {report.title} <span className="state__meta">({report.status})</span>
      </h2>
      <p className="state__meta">
        id <code>{report.id}</code> · kind {report.kind} · subject {report.subject_type}:
        {report.subject_id}
      </p>
      {(report.missing_sections ?? []).length > 0 ? (
        <p className="state__hint">
          Missing sections (content dependency unreachable, never fabricated):{" "}
          {(report.missing_sections ?? []).join(", ")}
        </p>
      ) : null}
      <StatementList title="Evidence" items={report.evidence} />
      <StatementList title="Findings" items={report.findings} />
      <StatementList title="Recommendations" items={report.recommendations} />
      {report.provenance && report.provenance.length > 0 ? (
        <p className="state__meta">Provenance: {report.provenance.join(", ")}</p>
      ) : null}
    </div>
  );
}

function StatementList({ title, items }: { title: string; items?: GroundedStatement[] }) {
  if (!items || items.length === 0) return null;
  return (
    <div>
      <h3>{title}</h3>
      <ul>
        {items.map((s, i) => (
          <li key={i} className="state__hint">
            <GroundingTag tier={s.tier} /> {s.text}
          </li>
        ))}
      </ul>
    </div>
  );
}

function LibraryPanel({ reports }: { reports: Report[] }) {
  return (
    <div className="panel">
      <h2>This session&rsquo;s reports</h2>
      <p className="state__hint">
        There is no server-side report listing yet — this is every report generated in this
        browser session. Use &ldquo;Look up a report&rdquo; below with an id from elsewhere.
      </p>
      {reports.length === 0 ? (
        <EmptyState title="No reports generated yet" />
      ) : (
        <table className="data">
          <thead>
            <tr>
              <th>Title</th>
              <th>Kind</th>
              <th>Status</th>
              <th>id</th>
            </tr>
          </thead>
          <tbody>
            {reports.map((r) => (
              <tr key={r.id}>
                <td>{r.title}</td>
                <td>{r.kind}</td>
                <td>{r.status}</td>
                <td>
                  <code>{r.id}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function LookupPanel() {
  const [id, setId] = useState("");
  const [result, setResult] = useState<Async<ReportDownload>>({ status: "idle" });

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!id.trim()) return;
    setResult({ status: "loading" });
    try {
      const data = await api.getReport(id.trim());
      setResult({ status: "done", data });
    } catch (e) {
      setResult({ status: "error", error: e instanceof Error ? e : new Error(String(e)) });
    }
  }

  return (
    <>
      <div className="panel">
        <h2>Look up a report</h2>
        <form onSubmit={onSubmit} style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label className="field" style={{ minWidth: 320 }}>
            <span>Report id</span>
            <input value={id} onChange={(e) => setId(e.target.value)} placeholder="report uuid" />
          </label>
          <button type="submit" className="btn">
            Look up
          </button>
        </form>
      </div>

      {result.status === "loading" ? <Loading label="Looking up report…" /> : null}
      {result.status === "error" ? <ErrorState error={result.error} /> : null}
      {result.status === "done" ? (
        <div className="panel">
          <ReportSummary report={result.data.report} />
          {result.data.download_url ? (
            <p>
              <a href={result.data.download_url} target="_blank" rel="noreferrer" className="btn btn--ghost">
                Download PDF (link expires shortly)
              </a>
            </p>
          ) : (
            <p className="state__hint">No PDF yet — the report is still {result.data.report.status}.</p>
          )}
        </div>
      ) : null}
    </>
  );
}
