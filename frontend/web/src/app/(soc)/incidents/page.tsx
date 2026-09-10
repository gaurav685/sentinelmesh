"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { DataView } from "@/components/DataView";
import { Severity } from "@/components/Severity";

export default function IncidentsPage() {
  const res = useResource((signal) => api.alerts({ limit: 100 }, signal));

  return (
    <div className="grid">
      <h1>Incidents</h1>
      <p className="state__hint">
        An incident is a security alert with its lifecycle — open, acknowledged, closed.
      </p>
      <div className="panel">
        <DataView
          resource={res}
          isEmpty={(d) => d.items.length === 0}
          emptyTitle="No incidents"
          emptyHint="Alerts are raised from high- and critical-severity detections."
        >
          {(d) => (
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
                {d.items.map((a) => (
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
        </DataView>
      </div>
    </div>
  );
}
