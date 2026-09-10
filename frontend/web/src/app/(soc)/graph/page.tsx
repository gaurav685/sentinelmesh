"use client";

import { type FormEvent, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { DataView } from "@/components/DataView";
import { AttackGraph, type GraphSelection } from "@/components/AttackGraph";

const LABELS = [
  "Identity",
  "Host",
  "Process",
  "File",
  "Network",
  "AttackChain",
  "AttackTechnique",
];

interface Q {
  label: string;
  key: string;
  depth: number;
}

export default function GraphPage() {
  const [form, setForm] = useState<Q>({ label: "Identity", key: "", depth: 2 });
  const [query, setQuery] = useState<Q | null>(null);
  const [selected, setSelected] = useState<GraphSelection | null>(null);

  const res = useResource(
    (signal) =>
      query
        ? api.graphNeighbors(
            { label: query.label, key: query.key, depth: query.depth },
            signal,
          )
        : Promise.resolve(null),
    [query?.label, query?.key, query?.depth],
  );

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const key = form.key.trim();
    if (!key) return;
    setSelected(null);
    setQuery({ ...form, key });
  }

  const nodes = useMemo(() => res.data?.nodes ?? [], [res.data]);
  const edges = useMemo(() => res.data?.edges ?? [], [res.data]);

  return (
    <div className="grid">
      <h1>Attack graph</h1>
      <p className="state__hint">
        Explore the real entity graph around a node. Traversal is depth-bounded and
        row-capped server-side and scoped to your tenant. Nothing here is synthetic —
        an empty result means no such relationships have been observed.
      </p>

      <form
        className="panel"
        onSubmit={onSubmit}
        style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}
      >
        <label className="field">
          <span>Node type</span>
          <select
            value={form.label}
            onChange={(e) => setForm((f) => ({ ...f, label: e.target.value }))}
          >
            {LABELS.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <label className="field" style={{ minWidth: 260 }}>
          <span>Natural key (identity id, hostname, hash…)</span>
          <input
            value={form.key}
            onChange={(e) => setForm((f) => ({ ...f, key: e.target.value }))}
          />
        </label>
        <label className="field" style={{ maxWidth: 120 }}>
          <span>Depth</span>
          <select
            value={form.depth}
            onChange={(e) => setForm((f) => ({ ...f, depth: Number(e.target.value) }))}
          >
            {[1, 2, 3, 4].map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="btn">
          Explore
        </button>
      </form>

      {query ? (
        <DataView
          resource={res}
          isEmpty={(d) => (d?.nodes ?? []).length === 0}
          emptyTitle="No graph data for this node"
          emptyHint="Either the node does not exist for your tenant or no relationships have been written for it yet."
        >
          {(d) => (
            <>
              {d?.truncated ? (
                <p className="state__meta" role="status">
                  The server row cap was hit — this view is partial. Narrow the depth for a
                  complete neighbourhood.
                </p>
              ) : null}
              <div className="graph-layout">
                <div className="panel">
                  <AttackGraph
                    nodes={nodes}
                    edges={edges}
                    selectedId={selected?.id ?? null}
                    onSelect={setSelected}
                  />
                </div>
                <div className="panel">
                  <h2>Selection</h2>
                  {selected ? (
                    <>
                      <p>
                        <strong>{selected.labels.join(", ") || selected.kind}</strong>
                      </p>
                      <p
                        className="state__meta"
                        style={{ fontFamily: "ui-monospace, monospace" }}
                      >
                        {selected.id}
                      </p>
                      <table className="data">
                        <tbody>
                          {Object.entries(selected.properties).map(([k, v]) => (
                            <tr key={k}>
                              <th style={{ textAlign: "left" }}>{k}</th>
                              <td>{String(v)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </>
                  ) : (
                    <p className="state__hint">Select a node in the graph or the list below.</p>
                  )}
                </div>
              </div>

              <div className="panel">
                <h2>Nodes ({nodes.length})</h2>
                <ul className="node-list">
                  {nodes.map((n) => (
                    <li key={n.id}>
                      <button
                        type="button"
                        className="btn btn--ghost"
                        aria-pressed={selected?.id === n.id}
                        onClick={() =>
                          setSelected({
                            kind: "node",
                            id: n.id,
                            labels: n.labels ?? [],
                            properties: (n.properties ?? {}) as Record<string, unknown>,
                          })
                        }
                      >
                        {(n.labels ?? []).join(":") || "Node"} —{" "}
                        {String((n.properties ?? {}).name ?? (n.properties ?? {}).key ?? n.id)}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="panel">
                <h2>Edges ({edges.length})</h2>
                <table className="data">
                  <thead>
                    <tr>
                      <th>Source</th>
                      <th>Relationship</th>
                      <th>Target</th>
                    </tr>
                  </thead>
                  <tbody>
                    {edges.map((e, i) => (
                      <tr key={`${e.src}-${e.type}-${e.dst}-${i}`}>
                        <td>{e.src}</td>
                        <td>{e.type}</td>
                        <td>{e.dst}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </DataView>
      ) : (
        <p className="state__hint">Enter a node above to explore its neighbourhood.</p>
      )}
    </div>
  );
}
