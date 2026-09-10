"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { DataView } from "@/components/DataView";

function band(score: number): { label: string; className: string } {
  if (score >= 0.9) return { label: "Critical", className: "sev sev--critical" };
  if (score >= 0.75) return { label: "High", className: "sev sev--high" };
  if (score >= 0.55) return { label: "Elevated", className: "sev sev--medium" };
  if (score >= 0.3) return { label: "Low", className: "sev sev--low" };
  return { label: "Minimal", className: "sev sev--info" };
}

export default function HeatmapPage() {
  const res = useResource((signal) => api.risk({ limit: 100 }, signal));

  return (
    <div className="grid">
      <h1>Risk heatmap</h1>
      <p className="state__hint">
        Every subject with a threat score, highest first. The score is a deterministic, versioned
        weighting — no validated performance is claimed.
      </p>
      <div className="panel">
        <DataView
          resource={res}
          isEmpty={(d) => d.length === 0}
          emptyTitle="No scored subjects"
          emptyHint="A subject gets a score once the correlation engine has processed a detection about it."
        >
          {(d) => (
            <table className="data">
              <thead>
                <tr>
                  <th>Subject</th>
                  <th>Type</th>
                  <th>Band</th>
                  <th>Score</th>
                  <th>Scoring</th>
                  <th>Computed</th>
                </tr>
              </thead>
              <tbody>
                {d.map((s) => {
                  const b = band(s.score);
                  return (
                    <tr key={`${s.subject_type}:${s.subject_id}`}>
                      <td>
                        <Link href={`/entities/${encodeURIComponent(s.subject_id)}`}>
                          {s.subject_id}
                        </Link>
                      </td>
                      <td>{s.subject_type}</td>
                      <td>
                        <span className={b.className}>{b.label}</span>
                      </td>
                      <td>{(s.score * 100).toFixed(0)}</td>
                      <td>{s.scoring_status}</td>
                      <td>{new Date(s.computed_at).toLocaleString()}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </DataView>
      </div>
    </div>
  );
}
