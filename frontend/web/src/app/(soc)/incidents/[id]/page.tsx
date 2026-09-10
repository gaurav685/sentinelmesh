"use client";

import { use } from "react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { DataView } from "@/components/DataView";
import { Severity } from "@/components/Severity";

export default function IncidentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const alertRes = useResource((signal) => api.alert(id, signal), [id]);

  return (
    <div className="grid">
      <h1>Incident</h1>
      <DataView resource={alertRes} isEmpty={() => false} emptyTitle="Incident not found">
        {(a) => <IncidentBody alert={a} />}
      </DataView>
    </div>
  );
}

function IncidentBody({ alert }: { alert: Awaited<ReturnType<typeof api.alert>> }) {
  const detRes = useResource(
    (signal) => api.detection(alert.detection_id, signal),
    [alert.detection_id],
  );
  return (
    <>
      <div className="panel">
        <h2>
          <Severity value={alert.severity} /> {alert.title}
        </h2>
        <p className="state__meta">
          {alert.status} · opened {new Date(alert.opened_at).toLocaleString()}
          {alert.acknowledged_at
            ? ` · acknowledged ${new Date(alert.acknowledged_at).toLocaleString()}`
            : ""}
          {alert.closed_at ? ` · closed ${new Date(alert.closed_at).toLocaleString()}` : ""}
        </p>
        {alert.summary ? <p>{alert.summary}</p> : null}
      </div>

      <div className="panel">
        <h2>Triggering detection</h2>
        <DataView resource={detRes} isEmpty={() => false} emptyTitle="Detection unavailable">
          {(d) => (
            <>
              <p>
                <strong>{d.title}</strong>
                {d.rule_id ? <span className="state__meta"> · {d.rule_id}</span> : null}
              </p>
              <p>{d.description}</p>
              {(d.technique_ids ?? []).length > 0 ? (
                <p className="state__hint">ATT&CK techniques: {(d.technique_ids ?? []).join(", ")}</p>
              ) : null}
              <h3>Evidence</h3>
              <ul>
                {(d.evidence ?? []).map((e, i) => (
                  <li key={i}>
                    <strong>{e.kind}</strong> — {e.summary}{" "}
                    <span className="state__meta">({e.provenance})</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </DataView>
      </div>
    </>
  );
}
