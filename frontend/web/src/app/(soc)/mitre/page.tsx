"use client";

import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { DataView } from "@/components/DataView";

const TACTIC_NAME: Record<string, string> = {
  TA0043: "Reconnaissance",
  TA0042: "Resource Development",
  TA0001: "Initial Access",
  TA0002: "Execution",
  TA0003: "Persistence",
  TA0004: "Privilege Escalation",
  TA0005: "Defense Evasion",
  TA0006: "Credential Access",
  TA0007: "Discovery",
  TA0008: "Lateral Movement",
  TA0009: "Collection",
  TA0011: "Command and Control",
  TA0010: "Exfiltration",
  TA0040: "Impact",
};

export default function MitrePage() {
  const res = useResource((signal) => api.mitreHeatmap(signal));

  return (
    <div className="grid">
      <h1>MITRE ATT&amp;CK coverage</h1>
      <p className="state__hint">
        Techniques mapped to this tenant&apos;s detections and attack chains. The count is the number
        of distinct subjects a technique was seen on. Coverage reflects only what has been imported —
        no ATT&amp;CK data ships with the platform.
      </p>
      <div className="panel">
        <DataView
          resource={res}
          isEmpty={(d) => (d.cells ?? []).length === 0}
          emptyTitle="No technique mappings yet"
          emptyHint="Mappings appear once mitre-service has processed detections against an imported ATT&CK catalog."
        >
          {(d) => (
            <>
              {d.matrix_version ? (
                <p className="state__meta">ATT&amp;CK matrix version {d.matrix_version}</p>
              ) : (
                <p className="state__meta">No ATT&amp;CK catalog imported.</p>
              )}
              <table className="data">
                <thead>
                  <tr>
                    <th>Technique</th>
                    <th>Tactic</th>
                    <th>Subjects</th>
                  </tr>
                </thead>
                <tbody>
                  {(d.cells ?? []).map((c) => (
                    <tr key={c.technique_id}>
                      <td>
                        {c.technique_id}
                        {c.name ? ` — ${c.name}` : ""}
                      </td>
                      <td>{c.tactic_id ? (TACTIC_NAME[c.tactic_id] ?? c.tactic_id) : "—"}</td>
                      <td>{c.subject_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </DataView>
      </div>
    </div>
  );
}
