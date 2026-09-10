"use client";

import { type FormEvent, useState } from "react";
import type { HuntResult, QueryPlan, SocHuntResponse } from "@sentinelmesh/contracts";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ErrorState, Loading } from "@/components/states";

const INTENTS = [
  "find_entity",
  "list_related",
  "path_between",
  "detections_for",
  "chains_for",
  "indicator_sightings",
  "technique_usage",
] as const;

const ENTITY_TYPES = [
  "identity",
  "host",
  "ip",
  "domain",
  "process",
  "file",
  "detection",
  "attack_chain",
  "attack_technique",
  "threat_actor",
  "campaign",
] as const;

type EntityType = (typeof ENTITY_TYPES)[number];

// graph node label -> the hunt entity type, for the "pivot" action
const LABEL_TO_TYPE: Record<string, EntityType> = {
  Identity: "identity",
  Host: "host",
  IpAddress: "ip",
  Domain: "domain",
  Process: "process",
  File: "file",
  Detection: "detection",
  AttackChain: "attack_chain",
  AttackTechnique: "attack_technique",
};
const TYPE_KEY: Record<EntityType, string> = {
  identity: "identity_id",
  host: "host_id",
  ip: "ip",
  domain: "fqdn",
  process: "process_id",
  file: "file_id",
  detection: "detection_id",
  attack_chain: "chain_id",
  attack_technique: "technique_id",
  threat_actor: "actor_id",
  campaign: "campaign_id",
};

export default function HuntPage() {
  const { csrfToken } = useAuth();
  const [mode, setMode] = useState<"ask" | "quick">("ask");
  const [nl, setNl] = useState("");
  const [intent, setIntent] = useState<(typeof INTENTS)[number]>("list_related");
  const [etype, setEtype] = useState<EntityType>("host");
  const [evalue, setEvalue] = useState("");
  const [state, setState] = useState<
    { status: "idle" } | { status: "loading" } | { status: "error"; error: Error }
    | { status: "done"; res: SocHuntResponse }
  >({ status: "idle" });

  async function runPlan(plan: QueryPlan | null, query: string | null) {
    setState({ status: "loading" });
    try {
      const res = await api.hunt(plan ? { plan } : { query: query ?? "" }, csrfToken);
      setState({ status: "done", res });
    } catch (e) {
      setState({ status: "error", error: e instanceof Error ? e : new Error(String(e)) });
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (mode === "ask") {
      if (nl.trim()) void runPlan(null, nl.trim());
      return;
    }
    const v = evalue.trim();
    if (!v) return;
    void runPlan(
      {
        intent,
        selectors: [{ type: etype, value: v }],
        rel_types: [],
        limits: { max_depth: 2, max_rows: 100 },
      },
      null,
    );
  }

  function pivot(row: Record<string, unknown>) {
    const labels = Array.isArray(row.labels) ? (row.labels as string[]) : [];
    const props = (row.properties ?? {}) as Record<string, unknown>;
    const label = labels.find((l) => l in LABEL_TO_TYPE);
    if (!label) return;
    const t = LABEL_TO_TYPE[label]!;
    const key = props[TYPE_KEY[t]];
    if (key == null) return;
    void runPlan(
      {
        intent: "list_related",
        selectors: [{ type: t, value: String(key) }],
        rel_types: [],
        limits: { max_depth: 2, max_rows: 100 },
      },
      null,
    );
  }

  return (
    <div className="grid">
      <h1>Threat hunting</h1>
      <p className="state__hint">
        Ask in plain language, or build a structured query. Either way the platform
        compiles it to a <strong>predefined, parameterized</strong> graph query scoped to
        your tenant — a natural-language question never becomes a raw query, and the exact
        plan that ran is shown below.
      </p>

      <div className="panel">
        <div className="tabs">
          <button
            type="button"
            className={mode === "ask" ? "tab tab--on" : "tab"}
            onClick={() => setMode("ask")}
          >
            Ask
          </button>
          <button
            type="button"
            className={mode === "quick" ? "tab tab--on" : "tab"}
            onClick={() => setMode("quick")}
          >
            Quick query
          </button>
        </div>

        <form onSubmit={onSubmit} className="grid" style={{ marginTop: 12 }}>
          {mode === "ask" ? (
            <label className="field">
              <span>Question</span>
              <input
                value={nl}
                onChange={(e) => setNl(e.target.value)}
                placeholder="e.g. what talks to host web01"
                aria-label="Question"
              />
            </label>
          ) : (
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
              <label className="field">
                <span>Intent</span>
                <select value={intent} onChange={(e) => setIntent(e.target.value as typeof intent)}>
                  {INTENTS.map((i) => (
                    <option key={i} value={i}>
                      {i}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Entity type</span>
                <select value={etype} onChange={(e) => setEtype(e.target.value as EntityType)}>
                  {ENTITY_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field" style={{ minWidth: 220 }}>
                <span>Value</span>
                <input value={evalue} onChange={(e) => setEvalue(e.target.value)} aria-label="Value" />
              </label>
            </div>
          )}
          <button type="submit" className="btn" style={{ width: "fit-content" }}>
            Run hunt
          </button>
        </form>
      </div>

      {state.status === "loading" ? <Loading label="Running the hunt…" /> : null}
      {state.status === "error" ? (
        <ErrorState error={state.error} />
      ) : null}
      {state.status === "done" ? <Result res={state.res} onPivot={pivot} /> : null}
    </div>
  );
}

function Result({
  res,
  onPivot,
}: {
  res: SocHuntResponse;
  onPivot: (row: Record<string, unknown>) => void;
}) {
  if (!res.supported || !res.result) {
    return (
      <div className="panel">
        <p className="state__title">Could not run that as a hunt</p>
        <p className="state__hint">
          {res.unsupported_reason || "The request could not be expressed as a supported query."}
        </p>
      </div>
    );
  }
  const r: HuntResult = res.result;
  const rows = (r.rows ?? []) as Record<string, unknown>[];
  return (
    <>
      <div className="panel">
        <h2>Result</h2>
        {r.explanation ? <p>{r.explanation}</p> : null}
        <p className="state__meta">
          intent <code>{r.intent}</code> · {r.row_count} row(s)
          {r.truncated ? " · truncated at the row cap" : ""} · query{" "}
          <code>{(r.cypher_fingerprint ?? "").slice(0, 12)}</code>
        </p>
      </div>

      <details className="panel">
        <summary>Compiled query plan</summary>
        <pre style={{ overflowX: "auto" }}>{JSON.stringify(r.plan, null, 2)}</pre>
      </details>

      <div className="panel">
        <h2>Rows</h2>
        {rows.length === 0 ? (
          <p className="state__hint">No matches — nothing has been observed for that query.</p>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Labels</th>
                <th>Properties</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i}>
                  <td>{Array.isArray(row.labels) ? (row.labels as string[]).join(":") : "—"}</td>
                  <td style={{ fontFamily: "ui-monospace, monospace" }}>
                    {JSON.stringify(row.properties ?? row)}
                  </td>
                  <td>
                    <button type="button" className="btn btn--ghost" onClick={() => onPivot(row)}>
                      Pivot
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
