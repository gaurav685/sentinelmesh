import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const { getNarrative } = vi.hoisted(() => ({ getNarrative: vi.fn() }));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: { getNarrative },
}));

import StoryPage from "./page";

afterEach(() => vi.clearAllMocks());

const NARRATIVE = {
  id: "n1", tenant_id: "t1", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  chain_id: "c1", subject_type: "host", subject_id: "web01",
  beats: [
    {
      at: "2026-01-01T00:00:00Z", stage: "initial_access", title: "Initial Access",
      detection_ids: ["d1"], technique_ids: ["T1110"], detection_count: 1, tier: "evidence",
    },
  ],
  summary: "The attacker gained a foothold.",
  cited_refs: ["initial_access"], confidence: "low", model: {}, degraded: true,
  degraded_reason: "llm_disabled", simulated: false, generated_at: "2026-01-01T00:00:00Z",
};

describe("StoryPage", () => {
  it("narrates a chain and renders its beats", async () => {
    getNarrative.mockResolvedValue(NARRATIVE);
    render(<StoryPage />);

    await userEvent.type(screen.getByPlaceholderText("chain uuid"), "c1");
    await userEvent.click(screen.getByRole("button", { name: "Narrate" }));

    expect(getNarrative).toHaveBeenCalledWith("c1");
    await waitFor(() => expect(screen.getByText("The attacker gained a foothold.")).toBeInTheDocument());
    expect(screen.getByText("Initial Access", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Evidence")).toBeInTheDocument();
    expect(screen.queryByText("Simulation")).not.toBeInTheDocument();
  });

  it("badges a simulated chain", async () => {
    getNarrative.mockResolvedValue({
      ...NARRATIVE,
      simulated: true,
      beats: [{ ...NARRATIVE.beats[0], tier: "synthetic" }],
    });
    render(<StoryPage />);

    await userEvent.type(screen.getByPlaceholderText("chain uuid"), "c2");
    await userEvent.click(screen.getByRole("button", { name: "Narrate" }));

    await waitFor(() => expect(screen.getByText("Simulation")).toBeInTheDocument());
    expect(screen.getByText("Synthetic")).toBeInTheDocument();
  });

  it("shows an empty state when the chain has no recorded stages", async () => {
    getNarrative.mockResolvedValue({ ...NARRATIVE, beats: [] });
    render(<StoryPage />);

    await userEvent.type(screen.getByPlaceholderText("chain uuid"), "c3");
    await userEvent.click(screen.getByRole("button", { name: "Narrate" }));

    await waitFor(() =>
      expect(screen.getByText("No kill-chain stages recorded for this chain yet")).toBeInTheDocument(),
    );
  });
});
