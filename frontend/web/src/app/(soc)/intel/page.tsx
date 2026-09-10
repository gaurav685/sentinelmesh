"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { DataView } from "@/components/DataView";

const TYPES = ["", "ipv4", "ipv6", "domain", "url", "sha256", "sha1", "md5", "email"];

export default function IntelPage() {
  const [type, setType] = useState("");
  const res = useResource(
    (signal) => api.tiIndicators({ type: type || undefined, limit: 200 }, signal),
    [type],
  );

  return (
    <div className="grid">
      <h1>Threat intelligence</h1>
      <p className="state__hint">
        Indicators available to this tenant (platform feeds plus tenant submissions). Freshness is
        derived on read; an expired indicator is not a match.
      </p>
      <div className="panel">
        <label className="field" style={{ maxWidth: 220 }}>
          <span>Type</span>
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {TYPES.map((t) => (
              <option key={t || "all"} value={t}>
                {t || "All"}
              </option>
            ))}
          </select>
        </label>

        <DataView
          resource={res}
          isEmpty={(d) => d.indicators.length === 0}
          emptyTitle="No indicators"
          emptyHint="External provider adapters are feature-flagged off by default; a platform operator enables them."
        >
          {(d) => (
            <table className="data">
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Value</th>
                  <th>Confidence</th>
                  <th>Reputation</th>
                  <th>Freshness</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {d.indicators.map((i) => (
                  <tr key={i.id}>
                    <td>{i.type}</td>
                    <td style={{ fontFamily: "ui-monospace, monospace" }}>{i.value}</td>
                    <td>{i.confidence}</td>
                    <td>{(i.reputation * 100).toFixed(0)}</td>
                    <td>{i.freshness}</td>
                    <td>{i.source}</td>
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
