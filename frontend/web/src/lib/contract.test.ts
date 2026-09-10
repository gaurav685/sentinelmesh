import { describe, expect, it } from "vitest";
import type { AttackChainModel, Detection, SocSummary } from "@sentinelmesh/contracts";

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
});
