"use client";

import { type FormEvent, useState } from "react";
import type { BlastRadiusResult, ScenarioRunResult, TwinSnapshot } from "@sentinelmesh/contracts";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ErrorState, Loading } from "@/components/states";

const KINDS = ["apt", "ransomware", "insider", "brute_force"] as const;

type Async<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; error: Error }
  | { status: "done"; data: T };

export default function SimulationPage() {
  const { csrfToken } = useAuth();

  const [seed, setSeed] = useState(1);
  const [name, setName] = useState("drill");
  const [kind, setKind] = useState<(typeof KINDS)[number]>("brute_force");
  const [targetHost, setTargetHost] = useState("sim-host-00");
  const [targetIdentity, setTargetIdentity] = useState("sim-id-alice");
  const [intensity, setIntensity] = useState(2);
  const [feedPipeline, setFeedPipeline] = useState(false);
  const [run, setRun] = useState<Async<ScenarioRunResult>>({ status: "idle" });

  const [twin, setTwin] = useState<Async<TwinSnapshot>>({ status: "idle" });
  const [blastSeed, setBlastSeed] = useState<string | null>(null);
  const [blast, setBlast] = useState<Async<BlastRadiusResult>>({ status: "idle" });

  async function onRun(e: FormEvent) {
    e.preventDefault();
    setRun({ status: "loading" });
    try {
      const data = await api.runScenario(
        {
          name,
          kind,
          seed,
          target_host: targetHost,
          target_identity: targetIdentity,
          intensity,
          feed_pipeline: feedPipeline,
        },
        csrfToken,
      );
      setRun({ status: "done", data });
    } catch (e) {
      setRun({ status: "error", error: e instanceof Error ? e : new Error(String(e)) });
    }
  }

  async function loadTwin() {
    setTwin({ status: "loading" });
    setBlast({ status: "idle" });
    setBlastSeed(null);
    try {
      const data = await api.twin(seed);
      setTwin({ status: "done", data });
    } catch (e) {
      setTwin({ status: "error", error: e instanceof Error ? e : new Error(String(e)) });
    }
  }

  async function runBlastRadius(assetId: string) {
    setBlastSeed(assetId);
    setBlast({ status: "loading" });
    try {
      const data = await api.blastRadius({ seed, seeds: [assetId], max_hops: 4 }, csrfToken);
      setBlast({ status: "done", data });
    } catch (e) {
      setBlast({ status: "error", error: e instanceof Error ? e : new Error(String(e)) });
    }
  }

  return (
    <div className="grid">
      <div className="page-head">
        <h1>
          Simulation
          <span className="demo-badge">Simulation</span>
        </h1>
      </div>
      <p className="state__hint">
        Every scenario here runs against a synthetic environment generated from a seed —
        never a real system. Every emitted event is marked <code>simulated: true</code>.
      </p>

      <div className="panel">
        <h2>Run a scenario</h2>
        <form onSubmit={onRun} className="grid" style={{ marginTop: 8 }}>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
            <label className="field">
              <span>Name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} />
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
              <span>Seed</span>
              <input
                type="number"
                min={0}
                value={seed}
                onChange={(e) => setSeed(Number(e.target.value))}
                style={{ width: 90 }}
              />
            </label>
            <label className="field">
              <span>Target host</span>
              <input value={targetHost} onChange={(e) => setTargetHost(e.target.value)} />
            </label>
            <label className="field">
              <span>Target identity</span>
              <input value={targetIdentity} onChange={(e) => setTargetIdentity(e.target.value)} />
            </label>
            <label className="field">
              <span>Intensity</span>
              <input
                type="number"
                min={1}
                max={5}
                value={intensity}
                onChange={(e) => setIntensity(Number(e.target.value))}
                style={{ width: 70 }}
              />
            </label>
            <label className="field" style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <input
                type="checkbox"
                checked={feedPipeline}
                onChange={(e) => setFeedPipeline(e.target.checked)}
              />
              <span>Feed the real detection pipeline (labelled simulated)</span>
            </label>
          </div>
          <button type="submit" className="btn" style={{ width: "fit-content" }}>
            Run scenario
          </button>
        </form>
      </div>

      {run.status === "loading" ? <Loading label="Running the scenario…" /> : null}
      {run.status === "error" ? <ErrorState error={run.error} /> : null}
      {run.status === "done" ? <ScenarioResult result={run.data} /> : null}

      <div className="panel">
        <h2>Digital twin</h2>
        <p className="state__hint">
          The twin is read off the same synthetic environment (seed <code>{seed}</code>) the
          scenario above runs against — pick an asset to see its blast radius.
        </p>
        <button type="button" className="btn btn--ghost" onClick={() => void loadTwin()}>
          Load twin for seed {seed}
        </button>
      </div>

      {twin.status === "loading" ? <Loading label="Building the twin…" /> : null}
      {twin.status === "error" ? <ErrorState error={twin.error} /> : null}
      {twin.status === "done" ? (
        <TwinView
          snapshot={twin.data}
          blastSeed={blastSeed}
          blast={blast}
          onPick={(id) => void runBlastRadius(id)}
        />
      ) : null}
    </div>
  );
}

function ScenarioResult({ result }: { result: ScenarioRunResult }) {
  return (
    <div className="panel">
      <h2>Result</h2>
      <p className="state__meta">
        scenario <code>{result.scenario_id}</code> · {result.event_count} event(s)
        {result.fed_to_pipeline ? ` · fed ${result.fed_event_count} to the pipeline` : ""}
      </p>
      {(result.events ?? []).length === 0 ? (
        <p className="state__hint">No events.</p>
      ) : (
        <table className="data">
          <thead>
            <tr>
              <th>Step</th>
              <th>+s</th>
              <th>Kind</th>
              <th>Actor</th>
              <th>Target</th>
            </tr>
          </thead>
          <tbody>
            {(result.events ?? []).slice(0, 50).map((e, i) => (
              <tr key={i}>
                <td>{e.step}</td>
                <td>{e.at_offset_s}</td>
                <td>{e.kind}</td>
                <td>{e.actor}</td>
                <td>{e.target}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function TwinView({
  snapshot,
  blastSeed,
  blast,
  onPick,
}: {
  snapshot: TwinSnapshot;
  blastSeed: string | null;
  blast: Async<BlastRadiusResult>;
  onPick: (assetId: string) => void;
}) {
  const reached = new Set(blast.status === "done" ? blast.data.reached ?? [] : []);
  const hopOf = blast.status === "done" ? blast.data.hop_of ?? {} : {};
  return (
    <>
      <div className="panel">
        <h2>Assets ({(snapshot.assets ?? []).length})</h2>
        <table className="data">
          <thead>
            <tr>
              <th>Id</th>
              <th>Kind</th>
              <th>Criticality</th>
              <th>Tags</th>
              <th>Blast radius</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(snapshot.assets ?? []).map((a) => (
              <tr key={a.id} aria-current={a.id === blastSeed ? "true" : undefined}>
                <td>{a.id}</td>
                <td>{a.kind}</td>
                <td>{a.criticality.toFixed(2)}</td>
                <td>{(a.tags ?? []).join(", ")}</td>
                <td>
                  {reached.has(a.id) ? (
                    <span className="sev sev--medium">reached (hop {hopOf[a.id] ?? "?"})</span>
                  ) : blastSeed ? (
                    "—"
                  ) : (
                    ""
                  )}
                </td>
                <td>
                  <button type="button" className="btn btn--ghost" onClick={() => onPick(a.id)}>
                    Blast radius
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {blast.status === "loading" ? <Loading label="Computing blast radius…" /> : null}
      {blast.status === "error" ? <ErrorState error={blast.error} /> : null}
      {blast.status === "done" ? (
        <div className="panel">
          <h2>Blast radius from {blastSeed}</h2>
          <p className="state__meta">
            score {blast.data.score.toFixed(3)} · reaches {(blast.data.reached ?? []).length}{" "}
            asset(s)
            {(blast.data.critical_reached ?? []).length > 0
              ? ` · ${(blast.data.critical_reached ?? []).length} critical`
              : ""}
          </p>
          {(blast.data.amplifying_weaknesses ?? []).length > 0 ? (
            <p className="state__hint">
              Amplifying weaknesses: {(blast.data.amplifying_weaknesses ?? []).join(", ")}
            </p>
          ) : null}
        </div>
      ) : null}

      {(snapshot.weaknesses ?? []).length > 0 ? (
        <div className="panel">
          <h2>Weaknesses</h2>
          <table className="data">
            <thead>
              <tr>
                <th>Asset</th>
                <th>Kind</th>
                <th>Severity</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {(snapshot.weaknesses ?? []).map((w, i) => (
                <tr key={i}>
                  <td>{w.asset_id}</td>
                  <td>{w.kind}</td>
                  <td>
                    <span className={`sev sev--${w.severity}`}>{w.severity}</span>
                  </td>
                  <td>{w.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </>
  );
}
