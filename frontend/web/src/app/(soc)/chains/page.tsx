"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { DataView } from "@/components/DataView";

export default function ChainsPage() {
  const res = useResource((signal) => api.chains({ limit: 100 }, signal));

  return (
    <div className="grid">
      <h1>Attack chains</h1>
      <div className="panel">
        <DataView
          resource={res}
          isEmpty={(d) => d.chains.length === 0}
          emptyTitle="No attack chains for this tenant"
          emptyHint="A chain forms when the correlation engine links two or more detections about one subject."
        >
          {(d) => (
            <table className="data">
              <thead>
                <tr>
                  <th>Subject</th>
                  <th>Status</th>
                  <th>Stages</th>
                  <th>Progression</th>
                  <th>Confidence</th>
                  <th>Score</th>
                </tr>
              </thead>
              <tbody>
                {d.chains.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <Link href={`/chains/${c.id}`}>{c.subject_id}</Link>
                      <span className="state__meta"> ({c.subject_type})</span>
                    </td>
                    <td>{c.status}</td>
                    <td>{c.distinct_stage_count}</td>
                    <td>{(c.progression * 100).toFixed(0)}%</td>
                    <td>{(c.confidence * 100).toFixed(0)}%</td>
                    <td>{(c.score * 100).toFixed(0)}</td>
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
