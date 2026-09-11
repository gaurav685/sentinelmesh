import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const { runScenario, twin, blastRadius } = vi.hoisted(() => ({
  runScenario: vi.fn(),
  twin: vi.fn(),
  blastRadius: vi.fn(),
}));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: { runScenario, twin, blastRadius },
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ csrfToken: "csrf-1" }) }));

import SimulationPage from "./page";

afterEach(() => vi.clearAllMocks());

describe("SimulationPage", () => {
  it("runs a scenario and renders its events", async () => {
    runScenario.mockResolvedValue({
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
    });
    render(<SimulationPage />);
    await userEvent.click(screen.getByRole("button", { name: "Run scenario" }));

    expect(runScenario).toHaveBeenCalledWith(
      expect.objectContaining({ name: "drill", kind: "brute_force", feed_pipeline: false }),
      "csrf-1",
    );
    await waitFor(() => expect(screen.getByText("scn-1")).toBeInTheDocument());
    expect(screen.getByText("auth_failed")).toBeInTheDocument();
  });

  it("loads the twin and computes a blast radius for a picked asset", async () => {
    twin.mockResolvedValue({
      seed: 1,
      synthetic: true,
      assets: [{ id: "sim-host-00", kind: "host", name: "web00", criticality: 0.3, tags: ["web"] }],
      relations: [],
      weaknesses: [],
    });
    blastRadius.mockResolvedValue({
      seed: 1,
      seeds: ["sim-host-00"],
      reached: ["sim-host-00", "sim-ip-00"],
      hop_of: { "sim-host-00": 0, "sim-ip-00": 1 },
      critical_reached: [],
      score: 0.25,
      amplifying_weaknesses: [],
    });
    render(<SimulationPage />);
    await userEvent.click(screen.getByRole("button", { name: "Load twin for seed 1" }));
    await waitFor(() => expect(screen.getByText("sim-host-00")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Blast radius" }));
    expect(blastRadius).toHaveBeenCalledWith({ seed: 1, seeds: ["sim-host-00"], max_hops: 4 }, "csrf-1");
    await waitFor(() =>
      expect(screen.getByText("Blast radius from sim-host-00")).toBeInTheDocument(),
    );
    expect(screen.getByText(/score 0\.250/)).toBeInTheDocument();
  });
});
