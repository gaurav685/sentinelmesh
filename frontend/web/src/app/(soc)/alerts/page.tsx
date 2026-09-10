"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { EmptyState, ErrorState, Loading } from "@/components/states";
import { Severity } from "@/components/Severity";
import { LiveBadge } from "@/components/LiveBadge";

const STATUSES = ["", "open", "acknowledged", "closed"];
const REFRESH_MS = 30_000;

export default function AlertsPage() {
  const [status, setStatus] = useState("open");
  const res = useResource(
    (signal) => api.alerts({ limit: 100, status: status || undefined }, signal),
    [status],
    { refreshMs: REFRESH_MS },
  );

  return (
    <div className="grid">
      <div className="page-head">
        <h1>Alerts</h1>
        <LiveBadge updatedAt={res.updatedAt} refreshMs={REFRESH_MS} onRefresh={res.reload} />
      </div>
      <div className="panel">
        <label className="field" style={{ maxWidth: 220 }}>
          <span>Status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map((s) => (
              <option key={s || "all"} value={s}>
                {s || "All"}
              </option>
            ))}
          </select>
        </label>

        {res.loading ? (
          <Loading />
        ) : res.error ? (
          <ErrorState error={res.error} onRetry={res.reload} />
        ) : (res.data?.items ?? []).length === 0 ? (
          <EmptyState title="No alerts match this filter" hint="Try a different status." />
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Severity</th>
                <th>Title</th>
                <th>Status</th>
                <th>Opened</th>
              </tr>
            </thead>
            <tbody>
              {(res.data?.items ?? []).map((a) => (
                <tr key={a.id}>
                  <td>
                    <Severity value={a.severity} />
                  </td>
                  <td>
                    <Link href={`/incidents/${a.id}`}>{a.title}</Link>
                  </td>
                  <td>{a.status}</td>
                  <td>{new Date(a.opened_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
