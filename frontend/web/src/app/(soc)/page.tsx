"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { ErrorState, Loading } from "@/components/states";
import { Severity } from "@/components/Severity";
import { LiveBadge } from "@/components/LiveBadge";

const REFRESH_MS = 20_000;

export default function DashboardPage() {
  const summary = useResource((signal) => api.socSummary(signal), [], { refreshMs: REFRESH_MS });
  const alerts = useResource(
    (signal) => api.alerts({ limit: 8, status: "open" }, signal),
    [],
    { refreshMs: REFRESH_MS },
  );

  if (summary.loading) return <Loading label="Loading the dashboard…" />;
  if (summary.error) return <ErrorState error={summary.error} onRetry={summary.reload} />;

  const s = summary.data;
  const sev = s?.alerts_by_severity ?? {};

  return (
    <div className="grid">
      <div className="page-head">
        <h1>Overview</h1>
        <LiveBadge
          updatedAt={summary.updatedAt}
          refreshMs={REFRESH_MS}
          onRefresh={() => {
            summary.reload();
            alerts.reload();
          }}
        />
      </div>

      <div className="grid grid--metrics">
        <div className="panel">
          <div className="metric__value">{s?.open_alerts ?? 0}</div>
          <div className="metric__label">Open alerts</div>
        </div>
        <div className="panel">
          <div className="metric__value">{sev["critical"] ?? 0}</div>
          <div className="metric__label">Critical alerts</div>
        </div>
        <div className="panel">
          <div className="metric__value">{s?.active_chains ?? 0}</div>
          <div className="metric__label">Active attack chains</div>
        </div>
        <div className="panel">
          <div className="metric__value">{s?.detections_24h ?? 0}</div>
          <div className="metric__label">Detections (24h)</div>
        </div>
      </div>

      <section className="panel">
        <h2>Highest-risk subjects</h2>
        {(s?.top_risk_subjects ?? []).length === 0 ? (
          <p className="state__hint">No scored subjects yet.</p>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Subject</th>
                <th>Type</th>
                <th>Score</th>
              </tr>
            </thead>
            <tbody>
              {(s?.top_risk_subjects ?? []).map((r) => (
                <tr key={`${r.subject_type}:${r.subject_id}`}>
                  <td>
                    <Link href={`/entities/${encodeURIComponent(r.subject_id)}`}>{r.subject_id}</Link>
                  </td>
                  <td>{r.subject_type}</td>
                  <td>{(r.score * 100).toFixed(0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <h2>Recent open alerts</h2>
        {alerts.loading ? (
          <Loading />
        ) : alerts.error ? (
          <ErrorState error={alerts.error} onRetry={alerts.reload} />
        ) : (alerts.data?.items ?? []).length === 0 ? (
          <p className="state__hint">No open alerts.</p>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Severity</th>
                <th>Title</th>
                <th>Opened</th>
              </tr>
            </thead>
            <tbody>
              {(alerts.data?.items ?? []).map((a) => (
                <tr key={a.id}>
                  <td>
                    <Severity value={a.severity} />
                  </td>
                  <td>
                    <Link href={`/incidents/${a.id}`}>{a.title}</Link>
                  </td>
                  <td>{new Date(a.opened_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
