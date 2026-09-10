"use client";

import Link from "next/link";
import { use } from "react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { DataView } from "@/components/DataView";
import { Severity } from "@/components/Severity";

export default function EntityDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const subjectId = decodeURIComponent(id);
  const res = useResource((signal) => api.timeline(subjectId, { limit: 200 }, signal), [subjectId]);

  return (
    <div className="grid">
      <h1>Entity: {subjectId}</h1>
      <div className="panel">
        <h2>Timeline</h2>
        <DataView
          resource={res}
          isEmpty={(d) => (d.entries ?? []).length === 0}
          emptyTitle="No activity for this entity"
          emptyHint="Nothing has been detected involving this entity in the retained window."
        >
          {(d) => (
            <ol className="grid" style={{ listStyle: "none", padding: 0 }}>
              {(d.entries ?? []).map((e) => (
                <li key={`${e.kind}:${e.ref_id}`} className="panel">
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                    <span>
                      {e.severity ? <Severity value={e.severity} /> : null}{" "}
                      {e.kind === "detection" ? (
                        <Link href={`/incidents`}>{e.title}</Link>
                      ) : (
                        e.title
                      )}
                    </span>
                    <span className="state__meta">{new Date(e.at).toLocaleString()}</span>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </DataView>
      </div>
    </div>
  );
}
