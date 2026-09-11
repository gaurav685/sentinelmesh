import { describe, expect, it } from "vitest";
import type {
  AdversaryFingerprint,
  AttackChainModel,
  BlastRadiusResult,
  Campaign,
  Decoy,
  Detection,
  Narrative,
  Prediction,
  Report,
  ScenarioRunResult,
  SocHuntResponse,
  SocSummary,
  TwinSnapshot,
} from "@sentinelmesh/contracts";

/**
 * API-contract tests: a fixture that mirrors a real BFF response must satisfy the
 * generated type. If the backend contract changes and the types are regenerated,
 * a now-invalid fixture fails to compile here — the frontend cannot silently
 * drift from the backend.
 */
describe("generated contract types", () => {
  it("SocSummary matches a BFF /soc/summary response", () => {
    const summary: SocSummary = {
      generated_at: "2026-09-10T00:00:00Z",
      open_alerts: 4,
      alerts_by_severity: { critical: 1, high: 3 },
      active_chains: 2,
      detections_24h: 11,
      top_risk_subjects: [
        {
          subject_type: "identity",
          subject_id: "svc-backup",
          score: 0.72,
          scoring_status: "ok",
          computed_at: "2026-09-10T00:00:00Z",
        },
      ],
    };
    expect(summary.open_alerts).toBe(4);
  });

  it("AttackChainModel matches a BFF /soc/chains/{id} response", () => {
    const chain: AttackChainModel = {
      id: "c1",
      tenant_id: "t1",
      created_at: "2026-09-10T00:00:00Z",
      updated_at: "2026-09-10T00:00:00Z",
      subject_type: "host",
      subject_id: "web01",
      status: "active",
      window_start: "2026-09-10T00:00:00Z",
      first_seen: "2026-09-10T00:00:00Z",
      last_seen: "2026-09-10T00:05:00Z",
      stages: [],
      distinct_stage_count: 2,
      progression: 0.6,
      confidence: 0.7,
      score: 0.55,
      score_version: "v1",
      scoring_status: "ok",
      detection_count: 3,
    };
    expect(chain.score_version).toBe("v1");
  });

  it("Detection severity is one of the contract's values", () => {
    const severities: Detection["severity"][] = ["info", "low", "medium", "high", "critical"];
    expect(severities).toContain("critical");
  });

  it("SocHuntResponse matches a BFF /soc/hunt response", () => {
    const res: SocHuntResponse = {
      supported: true,
      unsupported_reason: "",
      history_id: "h1",
      result: {
        intent: "list_related",
        plan: {
          intent: "list_related",
          selectors: [{ type: "host", value: "web01" }],
          rel_types: [],
          limits: { max_depth: 2, max_rows: 100 },
        },
        rows: [{ id: "n1", labels: ["IpAddress"], properties: { ip: "10.0.0.9" } }],
        row_count: 1,
        truncated: false,
        cypher_fingerprint: "fp",
        explanation: "one related ip [rows]",
      },
    };
    expect(res.result?.intent).toBe("list_related");
  });

  it("ScenarioRunResult matches a BFF /soc/simulation/run response", () => {
    const result: ScenarioRunResult = {
      scenario_id: "scn-1",
      kind: "brute_force",
      seed: 1,
      target_host: "sim-host-00",
      target_identity: "sim-id-alice",
      intensity: 2,
      event_count: 1,
      events: [
        { step: 0, at_offset_s: 0, kind: "auth_failed", actor: "sim-ip-00", target: "sim-id-alice" },
      ],
      synthetic: true,
      fed_to_pipeline: false,
      fed_event_count: 0,
    };
    expect(result.synthetic).toBe(true);
  });

  it("TwinSnapshot and BlastRadiusResult match /soc/simulation/twin + /blast-radius", () => {
    const snapshot: TwinSnapshot = {
      seed: 1,
      synthetic: true,
      assets: [{ id: "sim-host-00", kind: "host", name: "web00", criticality: 0.3, tags: ["web"] }],
      relations: [{ src: "sim-host-00", dst: "sim-ip-00", kind: "connects_to", weight: 0.9 }],
      weaknesses: [{ asset_id: "sim-host-00", kind: "public_exposure", severity: "high", detail: "" }],
    };
    const blast: BlastRadiusResult = {
      seed: 1,
      seeds: ["sim-host-00"],
      reached: ["sim-host-00", "sim-ip-00"],
      hop_of: { "sim-host-00": 0, "sim-ip-00": 1 },
      critical_reached: [],
      score: 0.25,
      amplifying_weaknesses: [],
    };
    expect(snapshot.assets?.length).toBe(1);
    expect(blast.score).toBe(0.25);
  });

  it("Decoy's network_boundary excludes 'production' at the type level", () => {
    const decoy: Decoy = {
      id: "d1", tenant_id: "t1", name: "ssh-honeypot", kind: "honeypot_host",
      network_boundary: "isolated", status: "active", ttl_seconds: 3600,
      created_at: "2026-01-01T00:00:00Z",
    };
    expect(decoy.network_boundary).not.toBe("production");
  });

  it("Campaign and AdversaryFingerprint match memory-service responses", () => {
    const campaign: Campaign = {
      id: "c1", tenant_id: "t1", status: "active", chain_ids: ["ch1"],
      technique_ids: ["T1110"], first_seen: "2026-01-01T00:00:00Z", last_seen: "2026-01-01T00:00:00Z",
      created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    };
    const fingerprint: AdversaryFingerprint = {
      id: "f1", tenant_id: "t1", subject_type: "identity", subject_id: "svc-backup",
      technique_ids: ["T1110"], campaign_ids: ["c1"], first_seen: "2026-01-01T00:00:00Z",
      last_seen: "2026-01-01T00:00:00Z", created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    expect(campaign.status).toBe("active");
    expect(fingerprint.subject_id).toBe("svc-backup");
  });

  it("Prediction always carries confidence + evidence + model_version, never just a verdict", () => {
    const prediction: Prediction = {
      kind: "threat_trajectory", subject_type: null, subject_id: "c1", prediction: "escalating",
      confidence: 0.7, evidence: ["status=active"], features: {}, model_version: "heuristic-v1",
      generated_at: "2026-01-01T00:00:00Z",
    };
    expect(prediction.model_version).toBe("heuristic-v1");
    expect(prediction.subject_type).toBeNull();
  });

  it("Report's evidence/findings/recommendations each carry a grounding tier", () => {
    const report: Report = {
      id: "r1", tenant_id: "t1", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
      kind: "incident", status: "partial", subject_type: "host", subject_id: "web01",
      title: "Host incident", requested_by: "u1", generated_at: "2026-01-01T00:00:00Z",
      incident_metadata: {}, timeline: [], affected_assets: [], detection_ids: [],
      evidence: [{ text: "A detection fired.", tier: "evidence", ref: "d1" }],
      chain_ids: [], technique_ids: [], threat_score: null, findings: [], recommendations: [],
      confidence: null, provenance: ["detection-engine"], missing_sections: ["affected_assets"],
      storage_key: null,
    };
    expect(report.evidence?.[0].tier).toBe("evidence");
    expect(report.missing_sections).toContain("affected_assets");
  });

  it("Narrative's beats are deterministic and simulated is set for a synthetic chain", () => {
    const narrative: Narrative = {
      id: "n1", tenant_id: "t1", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
      chain_id: "c1", subject_type: "host", subject_id: "sim-host-01",
      beats: [{
        at: "2026-01-01T00:00:00Z", stage: "initial_access", title: "Initial Access",
        detection_ids: ["d1"], technique_ids: ["T1110"], detection_count: 1, tier: "synthetic",
      }],
      summary: "A foothold was gained.", cited_refs: ["initial_access"], confidence: "low",
      model: {}, degraded: true, degraded_reason: "llm_disabled", simulated: true,
      generated_at: "2026-01-01T00:00:00Z",
    };
    expect(narrative.simulated).toBe(true);
    expect(narrative.beats?.[0].tier).toBe("synthetic");
  });
});
