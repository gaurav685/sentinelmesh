"use client";

import { type FormEvent, useEffect, useState } from "react";
import type { BenchmarkExperiment } from "@sentinelmesh/contracts";
import { api } from "@/lib/api";
import { EmptyState, ErrorState, Loading } from "@/components/states";

type Async<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; error: Error }
  | { status: "done"; data: T };

export default function BenchmarksPage() {
  return (
    <div className="grid">
      <div className="page-head">
        <h1>Benchmarks</h1>
      </div>
      <p className="state__hint">
        Every row below is a real, executed benchmark run — a model scored against a real
        dataset file, never a placeholder. A run that has not actually happened does not
        appear here (Constitution §3).
      </p>

      <ListPanel />
      <LookupPanel />
    </div>
  );
}

function MetricsTable({ metrics }: { metrics: Record<string, number> | undefined }) {
  const entries = Object.entries(metrics ?? {});
  if (entries.length === 0) return null;
  return (
    <table className="data">
      <thead>
        <tr>
          {entries.map(([k]) => (
            <th key={k}>{k}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        <tr>
          {entries.map(([k, v]) => (
            <td key={k}>{v}</td>
          ))}
        </tr>
      </tbody>
    </table>
  );
}

function ExperimentSummary({ exp }: { exp: BenchmarkExperiment }) {
  return (
    <div className="panel">
      <h2>
        {exp.dataset_id} <span className="state__meta">({exp.model_name})</span>
      </h2>
      <p className="state__meta">
        id <code>{exp.id}</code> · seed {exp.seed} · preprocessing {exp.preprocessing_version}
      </p>
      <p className="state__meta">
        train {exp.n_train} rows ({exp.n_train_benign_used_for_fit} benign used for the fit) ·
        test {exp.n_test} rows ({exp.n_test_anomalous} anomalous)
      </p>
      <p className="state__meta">
        train sha256 <code>{exp.train_sha256.slice(0, 12)}…</code> · test sha256{" "}
        <code>{exp.test_sha256.slice(0, 12)}…</code>
      </p>
      <h3>Metrics</h3>
      <MetricsTable metrics={exp.metrics} />
      <p className="state__meta">generated {exp.generated_at}</p>
    </div>
  );
}

function ListPanel() {
  const [datasetId, setDatasetId] = useState("");
  const [list, setList] = useState<Async<BenchmarkExperiment[]>>({ status: "idle" });

  async function load() {
    setList({ status: "loading" });
    try {
      const data = await api.listBenchmarks(datasetId || undefined);
      setList({ status: "done", data });
    } catch (e) {
      setList({ status: "error", error: e instanceof Error ? e : new Error(String(e)) });
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId]);

  return (
    <div className="panel">
      <h2>Recent runs</h2>
      <label className="field" style={{ maxWidth: 220 }}>
        <span>Dataset id</span>
        <input
          value={datasetId}
          onChange={(e) => setDatasetId(e.target.value)}
          placeholder="nsl-kdd"
        />
      </label>
      {list.status === "loading" ? <Loading label="Loading benchmark runs…" /> : null}
      {list.status === "error" ? <ErrorState error={list.error} onRetry={() => void load()} /> : null}
      {list.status === "done" ? (
        list.data.length === 0 ? (
          <EmptyState
            title="No benchmark runs recorded"
            hint="A run appears here only after sm-ml-train benchmark ... --save-to-db is actually executed."
          />
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Dataset</th>
                <th>Model</th>
                <th>ROC-AUC</th>
                <th>F1</th>
                <th>Generated</th>
                <th>id</th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((e) => (
                <tr key={e.id}>
                  <td>{e.dataset_id}</td>
                  <td>{e.model_name}</td>
                  <td>{e.metrics?.roc_auc ?? "—"}</td>
                  <td>{e.metrics?.f1 ?? "—"}</td>
                  <td>{e.generated_at}</td>
                  <td>
                    <code>{e.id}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : null}
    </div>
  );
}

function LookupPanel() {
  const [id, setId] = useState("");
  const [result, setResult] = useState<Async<BenchmarkExperiment>>({ status: "idle" });

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!id.trim()) return;
    setResult({ status: "loading" });
    try {
      const data = await api.getBenchmark(id.trim());
      setResult({ status: "done", data });
    } catch (e) {
      setResult({ status: "error", error: e instanceof Error ? e : new Error(String(e)) });
    }
  }

  return (
    <>
      <div className="panel">
        <h2>Look up a run</h2>
        <form onSubmit={onSubmit} style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label className="field" style={{ minWidth: 320 }}>
            <span>Experiment id</span>
            <input value={id} onChange={(e) => setId(e.target.value)} placeholder="experiment uuid" />
          </label>
          <button type="submit" className="btn">
            Look up
          </button>
        </form>
      </div>

      {result.status === "loading" ? <Loading label="Looking up run…" /> : null}
      {result.status === "error" ? <ErrorState error={result.error} /> : null}
      {result.status === "done" ? <ExperimentSummary exp={result.data} /> : null}
    </>
  );
}
