"use client";

import { type FormEvent, useEffect, useState } from "react";
import type { Decoy, DecoyInteraction } from "@sentinelmesh/contracts";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { EmptyState, ErrorState, Loading } from "@/components/states";

const KINDS = ["honeypot_host", "honeytoken", "decoy_credential"] as const;
// "production" is deliberately not offered — the backend schema and a database
// CHECK both refuse it; this list only shows what can ever succeed.
const BOUNDARIES = ["isolated", "dmz-isolated"] as const;

type Async<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; error: Error }
  | { status: "done"; data: T };

export default function DeceptionPage() {
  const { csrfToken } = useAuth();

  const [name, setName] = useState("ssh-honeypot");
  const [kind, setKind] = useState<(typeof KINDS)[number]>("honeypot_host");
  const [boundary, setBoundary] = useState<(typeof BOUNDARIES)[number]>("isolated");
  const [registering, setRegistering] = useState(false);
  const [registerError, setRegisterError] = useState<Error | null>(null);

  const [list, setList] = useState<Async<Decoy[]>>({ status: "idle" });
  const [selected, setSelected] = useState<Decoy | null>(null);
  const [interactions, setInteractions] = useState<Async<DecoyInteraction[]>>({ status: "idle" });

  async function loadDecoys() {
    setList({ status: "loading" });
    try {
      const data = await api.decoys();
      setList({ status: "done", data });
    } catch (e) {
      setList({ status: "error", error: e instanceof Error ? e : new Error(String(e)) });
    }
  }

  useEffect(() => {
    void loadDecoys();
  }, []);

  async function onRegister(e: FormEvent) {
    e.preventDefault();
    setRegistering(true);
    setRegisterError(null);
    try {
      await api.registerDecoy({ name, kind, network_boundary: boundary }, csrfToken);
      await loadDecoys();
    } catch (e) {
      setRegisterError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setRegistering(false);
    }
  }

  async function onTeardown(id: string) {
    await api.teardownDecoy(id, csrfToken);
    if (selected?.id === id) setSelected(null);
    await loadDecoys();
  }

  async function onSelect(d: Decoy) {
    setSelected(d);
    setInteractions({ status: "loading" });
    try {
      const data = await api.decoyInteractions(d.id);
      setInteractions({ status: "done", data });
    } catch (e) {
      setInteractions({ status: "error", error: e instanceof Error ? e : new Error(String(e)) });
    }
  }

  return (
    <div className="grid">
      <div className="page-head">
        <h1>
          Deception
          <span className="demo-badge">Simulation</span>
        </h1>
      </div>
      <p className="state__hint">
        A decoy&apos;s network boundary can only be <code>isolated</code> or{" "}
        <code>dmz-isolated</code> — never production, enforced by the schema and a database
        constraint. Decoys carry no credential field. Interaction capture is one-way; teardown
        is idempotent and keeps the interaction history for audit.
      </p>

      <div className="panel">
        <h2>Register a decoy</h2>
        <form onSubmit={onRegister} className="grid" style={{ marginTop: 8 }}>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
            <label className="field">
              <span>Name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </label>
            <label className="field">
              <span>Kind</span>
              <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
                {KINDS.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Network boundary</span>
              <select
                value={boundary}
                onChange={(e) => setBoundary(e.target.value as typeof boundary)}
              >
                {BOUNDARIES.map((b) => (
                  <option key={b} value={b}>
                    {b}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {registerError ? <p className="form-error">{registerError.message}</p> : null}
          <button type="submit" className="btn" disabled={registering} style={{ width: "fit-content" }}>
            {registering ? "Registering…" : "Register decoy"}
          </button>
        </form>
      </div>

      {list.status === "loading" ? <Loading label="Loading decoys…" /> : null}
      {list.status === "error" ? <ErrorState error={list.error} onRetry={() => void loadDecoys()} /> : null}
      {list.status === "done" ? (
        list.data.length === 0 ? (
          <EmptyState title="No decoys registered" hint="Register one above to start capturing interactions." />
        ) : (
          <div className="panel">
            <h2>Decoys</h2>
            <table className="data">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Kind</th>
                  <th>Boundary</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {list.data.map((d) => (
                  <tr key={d.id} aria-current={selected?.id === d.id ? "page" : undefined}>
                    <td>{d.name}</td>
                    <td>{d.kind}</td>
                    <td>{d.network_boundary}</td>
                    <td>{d.status}</td>
                    <td>{new Date(d.created_at).toLocaleString()}</td>
                    <td style={{ display: "flex", gap: 6 }}>
                      <button type="button" className="btn btn--ghost" onClick={() => void onSelect(d)}>
                        Interactions
                      </button>
                      <button
                        type="button"
                        className="btn btn--ghost"
                        disabled={d.status === "torn_down"}
                        onClick={() => void onTeardown(d.id)}
                      >
                        Tear down
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : null}

      {selected ? (
        <div className="panel">
          <h2>Interactions — {selected.name}</h2>
          {interactions.status === "loading" ? <Loading label="Loading interactions…" /> : null}
          {interactions.status === "error" ? <ErrorState error={interactions.error} /> : null}
          {interactions.status === "done" ? (
            interactions.data.length === 0 ? (
              <p className="state__hint">No interactions captured yet.</p>
            ) : (
              <table className="data">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Technique hint</th>
                    <th>Captured</th>
                  </tr>
                </thead>
                <tbody>
                  {interactions.data.map((i) => (
                    <tr key={i.id}>
                      <td>{i.source}</td>
                      <td>{i.technique_hint ?? "—"}</td>
                      <td>{new Date(i.captured_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
