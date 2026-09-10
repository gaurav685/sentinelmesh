import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { chains } = vi.hoisted(() => ({ chains: vi.fn() }));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: { chains } }));
vi.mock("next/link", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import ChainsPage from "./page";

afterEach(() => vi.clearAllMocks());

describe("ChainsPage", () => {
  it("renders a row per chain from the BFF response", async () => {
    chains.mockResolvedValue({
      count: 1,
      chains: [
        {
          id: "c1",
          subject_id: "svc-backup",
          subject_type: "identity",
          status: "active",
          distinct_stage_count: 3,
          progression: 0.85,
          confidence: 0.7,
          score: 0.66,
        },
      ],
    });
    render(<ChainsPage />);
    await waitFor(() => expect(screen.getByText("svc-backup")).toBeInTheDocument());
    expect(screen.getByText("85%")).toBeInTheDocument();
    expect(screen.getByText("66")).toBeInTheDocument();
  });

  it("shows an empty state when there are no chains", async () => {
    chains.mockResolvedValue({ count: 0, chains: [] });
    render(<ChainsPage />);
    await waitFor(() =>
      expect(screen.getByText("No attack chains for this tenant")).toBeInTheDocument(),
    );
  });

  it("shows an error state when the BFF fails", async () => {
    const { ApiError } = await import("@/lib/api");
    chains.mockRejectedValue(new ApiError(503, "correlation-engine unreachable"));
    render(<ChainsPage />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("unavailable"));
  });
});
