"use client";

import { type FormEvent, useState } from "react";
import type { Narrative, NarrativeBeat } from "@sentinelmesh/contracts";
import { api } from "@/lib/api";
import { EmptyState, ErrorState, Loading } from "@/components/states";
import { GroundingTag } from "@/components/GroundingTag";

type Async<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; error: Error }
  | { status: "done"; data: T };

export default function StoryPage() {
  const [chainId, setChainId] = useState("");
  const [result, setResult] = useState<Async<Narrative>>({ status: "idle" });

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!chainId.trim()) return;
    setResult({ status: "loading" });
    try {
      const data = await api.getNarrative(chainId.trim());
      setResult({ status: "done", data });
    } catch (e) {
      setResult({ status: "error", error: e instanceof Error ? e : new Error(String(e)) });
    }
  }

  return (
    <div className="grid">
      <div className="page-head">
        <h1>Attack story</h1>
      </div>
      <p className="state__hint">
        A cinematic breach replay for one attack chain. Every beat&rsquo;s stage, detections, and
        techniques come straight from the chain itself — never touched by an LLM. The summary
        paragraph is the one narrated part, and it is grounded: every sentence must cite a beat,
        or it falls back to a plain factual walkthrough instead.
      </p>

      <div className="panel">
        <form onSubmit={onSubmit} style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label className="field" style={{ minWidth: 320 }}>
            <span>Attack chain id</span>
            <input value={chainId} onChange={(e) => setChainId(e.target.value)} placeholder="chain uuid" />
          </label>
          <button type="submit" className="btn">
            Narrate
          </button>
        </form>
      </div>

      {result.status === "loading" ? <Loading label="Narrating…" /> : null}
      {result.status === "error" ? <ErrorState error={result.error} /> : null}
      {result.status === "done" ? <NarrativeView narrative={result.data} /> : null}
    </div>
  );
}

function NarrativeView({ narrative }: { narrative: Narrative }) {
  const beats = narrative.beats ?? [];
  return (
    <>
      <div className="panel">
        <h2>
          Subject: {narrative.subject_type}:{narrative.subject_id}
          {narrative.simulated ? <span className="demo-badge">Simulation</span> : null}
        </h2>
        <p className="state__meta">
          confidence {narrative.confidence}
          {narrative.degraded ? " · no live LLM — factual template" : ""}
        </p>
        <p style={{ whiteSpace: "pre-wrap" }}>{narrative.summary}</p>
      </div>

      <div className="panel">
        <h2>Timeline</h2>
        {beats.length === 0 ? (
          <EmptyState title="No kill-chain stages recorded for this chain yet" />
        ) : (
          <ol className="grid" style={{ gap: 12 }}>
            {beats.map((b, i) => (
              <BeatCard key={i} beat={b} />
            ))}
          </ol>
        )}
      </div>
    </>
  );
}

function BeatCard({ beat }: { beat: NarrativeBeat }) {
  return (
    <li className="panel">
      <p className="state__title">
        {beat.title} <GroundingTag tier={beat.tier} />
      </p>
      <p className="state__meta">
        {new Date(beat.at).toLocaleString()} · {beat.detection_count} detection(s)
      </p>
      {(beat.technique_ids ?? []).length > 0 ? (
        <p className="state__hint">Techniques: {(beat.technique_ids ?? []).join(", ")}</p>
      ) : null}
    </li>
  );
}
