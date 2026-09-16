import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { detections } = vi.hoisted(() => ({ detections: vi.fn() }));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: { detections },
}));
vi.mock("next/link", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import DetectionsPage from "./page";

afterEach(() => vi.clearAllMocks());

describe("DetectionsPage", () => {
  it("renders a row per detection from the BFF response, rule-based and ML-driven alike", async () => {
    detections.mockResolvedValue({
      items: [
        {
          id: "d1",
          detector: "rule",
          rule_id: "rule.auth.failed_burst",
          title: "Repeated authentication failures for alice",
          severity: "high",
          score: 0.85,
          scoring_status: "degraded",
          status: "new",
          first_seen: "2026-09-16T00:00:00Z",
          last_seen: "2026-09-16T00:00:00Z",
        },
        {
          id: "d2",
          detector: "composite",
          title: "Anomalous network_flow activity for 10.50.0.61",
          severity: "medium",
          score: 0.59,
          scoring_status: "ok",
          status: "new",
          first_seen: "2026-09-16T00:00:00Z",
          last_seen: "2026-09-16T00:00:00Z",
        },
      ],
      limit: 100,
    });
    render(<DetectionsPage />);
    await waitFor(() =>
      expect(screen.getByText("Repeated authentication failures for alice")).toBeInTheDocument(),
    );
    expect(screen.getByText("Anomalous network_flow activity for 10.50.0.61")).toBeInTheDocument();
    expect(screen.getByText("rule.auth.failed_burst", { exact: false })).toBeInTheDocument();
  });

  it("shows an empty state when there are no detections", async () => {
    detections.mockResolvedValue({ items: [], limit: 100 });
    render(<DetectionsPage />);
    await waitFor(() =>
      expect(screen.getByText("No detections match this filter")).toBeInTheDocument(),
    );
  });

  it("shows an error state when the BFF fails", async () => {
    const { ApiError } = await import("@/lib/api");
    detections.mockRejectedValue(new ApiError(503, "detection-engine unreachable"));
    render(<DetectionsPage />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("unavailable"));
  });
});
