"use client";

import { use } from "react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { DataView } from "@/components/DataView";
import { Severity } from "@/components/Severity";

export default function DetectionDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const res = useResource((signal) => api.detection(id, signal), [id]);

  return (
    <div className="grid">
      <h1>Detection</h1>
      <DataView resource={res} isEmpty={() => false} emptyTitle="Detection not found">
        {(d) => (
          <div className="panel">
            <h2>
              <Severity value={d.severity} /> {d.title}
            </h2>
            <p className="state__meta">
              {d.detector}
              {d.rule_id ? ` · ${d.rule_id}` : ""} · score {d.score.toFixed(2)}
              {d.scoring_status !== "ok" ? ` (${d.scoring_status})` : ""} · {d.status} · first
              seen {new Date(d.first_seen).toLocaleString()}
            </p>
            {d.description ? <p>{d.description}</p> : null}
            {(d.entities ?? []).length > 0 ? (
              <p className="state__hint">
                Entities: {(d.entities ?? []).map((e) => `${e.kind}:${e.value}`).join(", ")}
              </p>
            ) : null}
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
          </div>
        )}
      </DataView>
    </div>
  );
}
