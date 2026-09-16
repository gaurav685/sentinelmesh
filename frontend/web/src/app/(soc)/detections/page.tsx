"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { EmptyState, ErrorState, Loading } from "@/components/states";
import { Severity } from "@/components/Severity";
import { LiveBadge } from "@/components/LiveBadge";

const SEVERITIES = ["", "critical", "high", "medium", "low", "info"];
const REFRESH_MS = 30_000;

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export default function DetectionsPage() {
  const [severity, setSeverity] = useState("");
  const res = useResource(
    (signal) => api.detections({ limit: 100, severity: severity || undefined }, signal),
    [severity],
    { refreshMs: REFRESH_MS },
  );

  return (
    <div className="grid">
      <div className="page-head">
        <h1>Detections</h1>
        <LiveBadge updatedAt={res.updatedAt} refreshMs={REFRESH_MS} onRefresh={res.reload} />
      </div>
      <p className="state__hint">
        Every finding the detection pipeline has raised — rule-based and ML-driven alike. Only
        high/critical-severity (or high-confidence) detections escalate to an{" "}
        <Link href="/incidents">incident</Link>; the rest surface here.
      </p>
      <div className="panel">
        <label className="field" style={{ maxWidth: 220 }}>
          <span>Severity</span>
          <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
            {SEVERITIES.map((s) => (
              <option key={s || "all"} value={s}>
                {s ? capitalize(s) : "All"}
              </option>
            ))}
          </select>
        </label>

        {res.loading ? (
          <Loading />
        ) : res.error ? (
          <ErrorState error={res.error} onRetry={res.reload} />
        ) : (res.data?.items ?? []).length === 0 ? (
          <EmptyState title="No detections match this filter" hint="Try a different severity." />
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Severity</th>
                <th>Title</th>
                <th>Detector</th>
                <th>Score</th>
                <th>Status</th>
                <th>First seen</th>
              </tr>
            </thead>
            <tbody>
              {(res.data?.items ?? []).map((d) => (
                <tr key={d.id}>
                  <td>
                    <Severity value={d.severity} />
                  </td>
                  <td>
                    <Link href={`/detections/${d.id}`}>{d.title}</Link>
                  </td>
                  <td>
                    {d.detector}
                    {d.rule_id ? <span className="state__meta"> · {d.rule_id}</span> : null}
                  </td>
                  <td>
                    {d.score.toFixed(2)}
                    {d.scoring_status !== "ok" ? (
                      <span className="state__meta"> ({d.scoring_status})</span>
                    ) : null}
                  </td>
                  <td>{d.status}</td>
                  <td>{new Date(d.first_seen).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
