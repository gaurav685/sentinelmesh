"use client";

import { type FormEvent, useEffect, useState } from "react";
import type {
  AdversaryFingerprint,
  Campaign,
  Prediction,
  SimilarityMatch,
  ThreatMemory,
} from "@sentinelmesh/contracts";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { EmptyState, ErrorState, Loading } from "@/components/states";

type Async<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; error: Error }
  | { status: "done"; data: T };

const SUBJECT_TYPES = ["identity", "host", "ip", "domain", "detection"] as const;
const SIMILARITY_KINDS = ["threat_memory", "campaign", "adversary_fingerprint"] as const;

export default function MemoryPage() {
  const { csrfToken } = useAuth();

  return (
    <div className="grid">
      <div className="page-head">
        <h1>Threat memory</h1>
      </div>
      <p className="state__hint">
        Three separate stores, never duplicated: the attack graph and knowledge graph stay in
        Neo4j; this page is the fourth — behavioral patterns, campaigns, and adversary
        fingerprints, in Postgres. Every prediction below is a deterministic rule, not a
        trained model — it always carries its own confidence and evidence.
      </p>

      <CampaignsPanel csrfToken={csrfToken} />
      <FingerprintPanel csrfToken={csrfToken} />
      <SimilarityPanel csrfToken={csrfToken} />
      <ChainPredictionPanel csrfToken={csrfToken} />
    </div>
  );
}

function PredictionCard({ prediction }: { prediction: Prediction }) {
  return (
    <div className="panel">
      <p className="state__meta">
        <code>{prediction.kind}</code> · confidence {prediction.confidence.toFixed(2)} · model{" "}
        <code>{prediction.model_version}</code>
      </p>
      <p className="state__title">{prediction.prediction}</p>
      {(prediction.evidence ?? []).length > 0 ? (
        <ul>
          {(prediction.evidence ?? []).map((e, i) => (
            <li key={i} className="state__hint">
              {e}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="state__hint">
        A deterministic heuristic, not a trained model — never a verified fact.
      </p>
    </div>
  );
}

function CampaignsPanel({ csrfToken }: { csrfToken: string | null }) {
  const [list, setList] = useState<Async<Campaign[]>>({ status: "idle" });
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<Campaign | null>(null);
  const [prediction, setPrediction] = useState<Async<Prediction>>({ status: "idle" });

  async function load() {
    setList({ status: "loading" });
    try {
      const data = await api.memCampaigns(status ? { status } : {});
      setList({ status: "done", data });
    } catch (e) {
      setList({ status: "error", error: e instanceof Error ? e : new Error(String(e)) });
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  async function predictTrajectory(c: Campaign) {
    setSelected(c);
    setPrediction({ status: "loading" });
    try {
      const data = await api.predictThreatTrajectory(c.id, csrfToken);
      setPrediction({ status: "done", data });
    } catch (e) {
      setPrediction({ status: "error", error: e instanceof Error ? e : new Error(String(e)) });
    }
  }

  return (
    <>
      <div className="panel">
        <h2>Campaigns</h2>
        <label className="field" style={{ maxWidth: 220 }}>
          <span>Status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">any</option>
            <option value="active">active</option>
            <option value="dormant">dormant</option>
            <option value="closed">closed</option>
          </select>
        </label>
        {list.status === "loading" ? <Loading label="Loading campaigns…" /> : null}
        {list.status === "error" ? <ErrorState error={list.error} onRetry={() => void load()} /> : null}
        {list.status === "done" ? (
          list.data.length === 0 ? (
            <EmptyState title="No campaigns recorded" hint="Campaigns form as attack chains are ingested." />
          ) : (
            <table className="data">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Chains</th>
                  <th>Techniques</th>
                  <th>Last seen</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {list.data.map((c) => (
                  <tr key={c.id}>
                    <td>{c.status}</td>
                    <td>{(c.chain_ids ?? []).length}</td>
                    <td>{(c.technique_ids ?? []).join(", ")}</td>
                    <td>{new Date(c.last_seen).toLocaleString()}</td>
                    <td>
                      <button type="button" className="btn btn--ghost" onClick={() => void predictTrajectory(c)}>
                        Predict trajectory
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        ) : null}
      </div>

      {prediction.status === "loading" ? <Loading label="Predicting…" /> : null}
      {prediction.status === "error" ? <ErrorState error={prediction.error} /> : null}
      {prediction.status === "done" && selected ? <PredictionCard prediction={prediction.data} /> : null}
    </>
  );
}

function FingerprintPanel({ csrfToken }: { csrfToken: string | null }) {
  const [subjectType, setSubjectType] = useState<(typeof SUBJECT_TYPES)[number]>("identity");
  const [subjectId, setSubjectId] = useState("");
  const [result, setResult] = useState<Async<AdversaryFingerprint>>({ status: "idle" });
  const [prediction, setPrediction] = useState<Async<Prediction>>({ status: "idle" });

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!subjectId.trim()) return;
    setResult({ status: "loading" });
    setPrediction({ status: "idle" });
    try {
      const data = await api.memFingerprint(subjectType, subjectId.trim());
      setResult({ status: "done", data });
    } catch (e) {
      setResult({ status: "error", error: e instanceof Error ? e : new Error(String(e)) });
    }
  }

  async function predictLateral() {
    setPrediction({ status: "loading" });
    try {
      const data = await api.predictLateralMovement(subjectType, subjectId.trim(), csrfToken);
      setPrediction({ status: "done", data });
    } catch (e) {
      setPrediction({ status: "error", error: e instanceof Error ? e : new Error(String(e)) });
    }
  }

  return (
    <>
      <div className="panel">
        <h2>Adversary fingerprint — &ldquo;seen before&rdquo;</h2>
        <form onSubmit={onSubmit} style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label className="field">
            <span>Subject type</span>
            <select value={subjectType} onChange={(e) => setSubjectType(e.target.value as typeof subjectType)}>
              {SUBJECT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label className="field" style={{ minWidth: 220 }}>
            <span>Subject id</span>
            <input value={subjectId} onChange={(e) => setSubjectId(e.target.value)} placeholder="svc-backup" />
          </label>
          <button type="submit" className="btn">
            Look up
          </button>
        </form>
      </div>

      {result.status === "loading" ? <Loading label="Looking up fingerprint…" /> : null}
      {result.status === "error" ? <ErrorState error={result.error} /> : null}
      {result.status === "done" ? (
        <div className="panel">
          <h2>Fingerprint</h2>
          <p className="state__meta">
            {(result.data.technique_ids ?? []).length} technique(s) ·{" "}
            {(result.data.campaign_ids ?? []).length} campaign(s) · last seen{" "}
            {new Date(result.data.last_seen).toLocaleString()}
          </p>
          <p>{(result.data.technique_ids ?? []).join(", ")}</p>
          <button type="button" className="btn btn--ghost" onClick={() => void predictLateral()}>
            Predict lateral movement
          </button>
        </div>
      ) : null}

      {prediction.status === "loading" ? <Loading label="Predicting…" /> : null}
      {prediction.status === "error" ? <ErrorState error={prediction.error} /> : null}
      {prediction.status === "done" ? <PredictionCard prediction={prediction.data} /> : null}
    </>
  );
}

function SimilarityPanel({ csrfToken }: { csrfToken: string | null }) {
  const [kind, setKind] = useState<(typeof SIMILARITY_KINDS)[number]>("threat_memory");
  const [techniqueIds, setTechniqueIds] = useState("T1110, T1078");
  const [result, setResult] = useState<Async<SimilarityMatch[]>>({ status: "idle" });

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const ids = techniqueIds.split(",").map((s) => s.trim()).filter(Boolean);
    if (ids.length === 0) return;
    setResult({ status: "loading" });
    try {
      const data = await api.memSimilar({ kind, technique_ids: ids }, csrfToken);
      setResult({ status: "done", data });
    } catch (e) {
      setResult({ status: "error", error: e instanceof Error ? e : new Error(String(e)) });
    }
  }

  return (
    <>
      <div className="panel">
        <h2>Similarity search</h2>
        <form onSubmit={onSubmit} style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label className="field">
            <span>Kind</span>
            <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
              {SIMILARITY_KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          </label>
          <label className="field" style={{ minWidth: 260 }}>
            <span>Technique ids (comma-separated)</span>
            <input value={techniqueIds} onChange={(e) => setTechniqueIds(e.target.value)} />
          </label>
          <button type="submit" className="btn">
            Search
          </button>
        </form>
      </div>

      {result.status === "loading" ? <Loading label="Searching…" /> : null}
      {result.status === "error" ? <ErrorState error={result.error} /> : null}
      {result.status === "done" ? (
        result.data.length === 0 ? (
          <EmptyState title="No matches" />
        ) : (
          <div className="panel">
            <table className="data">
              <thead>
                <tr>
                  <th>Score</th>
                  <th>Techniques</th>
                  <th>Last seen</th>
                  <th>Path</th>
                </tr>
              </thead>
              <tbody>
                {result.data.map((m) => (
                  <tr key={m.id}>
                    <td>{m.score.toFixed(3)}</td>
                    <td>{(m.technique_ids ?? []).join(", ")}</td>
                    <td>{new Date(m.last_seen).toLocaleString()}</td>
                    <td>{m.exact_fallback ? "exact-match fallback" : "pgvector index"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : null}
    </>
  );
}

function ChainPredictionPanel({ csrfToken }: { csrfToken: string | null }) {
  const [chainId, setChainId] = useState("");
  const [prediction, setPrediction] = useState<Async<Prediction>>({ status: "idle" });

  async function run(which: "progression" | "next") {
    if (!chainId.trim()) return;
    setPrediction({ status: "loading" });
    try {
      const data =
        which === "progression"
          ? await api.predictAttackProgression(chainId.trim(), csrfToken)
          : await api.predictNextAction(chainId.trim(), csrfToken);
      setPrediction({ status: "done", data });
    } catch (e) {
      setPrediction({ status: "error", error: e instanceof Error ? e : new Error(String(e)) });
    }
  }

  return (
    <>
      <div className="panel">
        <h2>Chain predictions</h2>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label className="field" style={{ minWidth: 280 }}>
            <span>Chain id</span>
            <input value={chainId} onChange={(e) => setChainId(e.target.value)} placeholder="chain uuid" />
          </label>
          <button type="button" className="btn" onClick={() => void run("progression")}>
            Predict attack progression
          </button>
          <button type="button" className="btn btn--ghost" onClick={() => void run("next")}>
            Predict next action
          </button>
        </div>
      </div>

      {prediction.status === "loading" ? <Loading label="Predicting…" /> : null}
      {prediction.status === "error" ? <ErrorState error={prediction.error} /> : null}
      {prediction.status === "done" ? <PredictionCard prediction={prediction.data} /> : null}
    </>
  );
}
