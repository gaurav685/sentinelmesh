"use client";

import { use } from "react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { DataView } from "@/components/DataView";
import { Severity } from "@/components/Severity";

export default function ChainDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const res = useResource((signal) => api.chain(id, signal), [id]);

  return (
    <div className="grid">
      <h1>Attack chain</h1>
      <DataView
        resource={res}
        isEmpty={() => false}
        emptyTitle="Chain not found"
      >
        {(c) => (
          <>
            <div className="panel grid grid--metrics">
              <div>
                <div className="metric__value">{c.status}</div>
                <div className="metric__label">Status</div>
              </div>
              <div>
                <div className="metric__value">{(c.progression * 100).toFixed(0)}%</div>
                <div className="metric__label">Progression</div>
              </div>
              <div>
                <div className="metric__value">{(c.confidence * 100).toFixed(0)}%</div>
                <div className="metric__label">Confidence (never certainty)</div>
              </div>
              <div>
                <div className="metric__value">{(c.score * 100).toFixed(0)}</div>
                <div className="metric__label">Threat score ({c.score_version})</div>
              </div>
            </div>

            <div className="panel">
              <h2>Subject</h2>
              <p>
                {c.subject_id} <span className="state__meta">({c.subject_type})</span>
              </p>
              <p className="state__meta">
                {new Date(c.first_seen).toLocaleString()} — {new Date(c.last_seen).toLocaleString()}
              </p>
              {(c.notes ?? []).length > 0 ? (
                <p className="state__hint">Notes: {(c.notes ?? []).join(", ")}</p>
              ) : null}
            </div>

            <div className="panel">
              <h2>Kill-chain stages</h2>
              <table className="data">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Stage</th>
                    <th>Detections</th>
                    <th>Max severity</th>
                    <th>First seen</th>
                  </tr>
                </thead>
                <tbody>
                  {(c.stages ?? []).map((st) => (
                    <tr key={st.stage}>
                      <td>{st.stage_order}</td>
                      <td>{st.stage}</td>
                      <td>{st.detection_count}</td>
                      <td>
                        <Severity value={st.max_severity} />
                      </td>
                      <td>{new Date(st.first_seen).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </DataView>
    </div>
  );
}
