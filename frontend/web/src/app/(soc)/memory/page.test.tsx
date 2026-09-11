import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const {
  memCampaigns, memFingerprint, memSimilar,
  predictAttackProgression, predictLateralMovement, predictThreatTrajectory,
} = vi.hoisted(() => ({
  memCampaigns: vi.fn(),
  memFingerprint: vi.fn(),
  memSimilar: vi.fn(),
  predictAttackProgression: vi.fn(),
  predictLateralMovement: vi.fn(),
  predictThreatTrajectory: vi.fn(),
}));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: {
    memCampaigns, memFingerprint, memSimilar,
    predictAttackProgression, predictLateralMovement, predictThreatTrajectory,
  },
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ csrfToken: "csrf-1" }) }));

import MemoryPage from "./page";

afterEach(() => vi.clearAllMocks());

const CAMPAIGN = {
  id: "c1", tenant_id: "t1", status: "active", chain_ids: ["ch1", "ch2"],
  technique_ids: ["T1110"], first_seen: "2026-01-01T00:00:00Z", last_seen: "2026-01-01T00:00:00Z",
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};
const PREDICTION = {
  kind: "threat_trajectory", subject_type: null, subject_id: "c1", prediction: "escalating",
  confidence: 0.7, evidence: ["status=active", "chain_count=2"], features: {},
  model_version: "heuristic-v1", generated_at: "2026-01-01T00:00:00Z",
};

describe("MemoryPage", () => {
  it("lists campaigns and predicts a trajectory", async () => {
    memCampaigns.mockResolvedValue([CAMPAIGN]);
    predictThreatTrajectory.mockResolvedValue(PREDICTION);
    render(<MemoryPage />);

    await waitFor(() => expect(screen.getByText("active")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Predict trajectory" }));

    expect(predictThreatTrajectory).toHaveBeenCalledWith("c1", "csrf-1");
    await waitFor(() => expect(screen.getByText("escalating")).toBeInTheDocument());
    expect(screen.getByText("heuristic-v1", { exact: false })).toBeInTheDocument();
  });

  it("looks up a fingerprint and predicts lateral movement", async () => {
    memCampaigns.mockResolvedValue([]);
    memFingerprint.mockResolvedValue({
      id: "f1", tenant_id: "t1", subject_type: "identity", subject_id: "svc-backup",
      technique_ids: ["T1110"], campaign_ids: ["c1"], first_seen: "2026-01-01T00:00:00Z",
      last_seen: "2026-01-01T00:00:00Z", created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    predictLateralMovement.mockResolvedValue({ ...PREDICTION, kind: "lateral_movement", prediction: "identity:web02" });
    render(<MemoryPage />);

    await userEvent.type(screen.getByPlaceholderText("svc-backup"), "svc-backup");
    await userEvent.click(screen.getByRole("button", { name: "Look up" }));
    await waitFor(() => expect(memFingerprint).toHaveBeenCalledWith("identity", "svc-backup"));

    await userEvent.click(screen.getByRole("button", { name: "Predict lateral movement" }));
    await waitFor(() => expect(screen.getByText("identity:web02")).toBeInTheDocument());
  });

  it("runs a similarity search", async () => {
    memCampaigns.mockResolvedValue([]);
    memSimilar.mockResolvedValue([
      { kind: "threat_memory", id: "p1", score: 0.9, technique_ids: ["T1110"], last_seen: "2026-01-01T00:00:00Z", exact_fallback: false },
    ]);
    render(<MemoryPage />);

    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(memSimilar).toHaveBeenCalledWith(
      { kind: "threat_memory", technique_ids: ["T1110", "T1078"] }, "csrf-1",
    );
    await waitFor(() => expect(screen.getByText("0.900")).toBeInTheDocument());
  });
});
