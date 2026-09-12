import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const { listBenchmarks, getBenchmark } = vi.hoisted(() => ({
  listBenchmarks: vi.fn(),
  getBenchmark: vi.fn(),
}));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: { listBenchmarks, getBenchmark },
}));

import BenchmarksPage from "./page";

afterEach(() => vi.clearAllMocks());

const EXPERIMENT = {
  id: "e1", dataset_id: "nsl-kdd", train_sha256: "a".repeat(64), test_sha256: "b".repeat(64),
  preprocessing_version: "nsl-kdd-v1", model_name: "mad_zscore", n_train: 125973,
  n_train_benign_used_for_fit: 67343, n_test: 22544, n_test_anomalous: 12833,
  params: { z_threshold: 3.5 }, seed: 1337,
  metrics: { roc_auc: 0.639039, f1: 0.627537 },
  environment: { python_version: "3.11.5" },
  executed: true, generated_at: "2026-09-12T15:42:36Z", created_at: "2026-09-12T15:42:36Z",
};

describe("BenchmarksPage", () => {
  it("lists real runs on load", async () => {
    listBenchmarks.mockResolvedValue([EXPERIMENT]);
    render(<BenchmarksPage />);

    await waitFor(() => expect(screen.getByText("nsl-kdd")).toBeInTheDocument());
    expect(screen.getByText("mad_zscore")).toBeInTheDocument();
    expect(screen.getByText("0.639039")).toBeInTheDocument();
  });

  it("shows an empty state when no run has ever executed", async () => {
    listBenchmarks.mockResolvedValue([]);
    render(<BenchmarksPage />);

    await waitFor(() =>
      expect(screen.getByText("No benchmark runs recorded")).toBeInTheDocument(),
    );
  });

  it("looks up a run by id", async () => {
    listBenchmarks.mockResolvedValue([]);
    getBenchmark.mockResolvedValue(EXPERIMENT);
    render(<BenchmarksPage />);

    await userEvent.type(screen.getByPlaceholderText("experiment uuid"), "e1");
    await userEvent.click(screen.getByRole("button", { name: "Look up" }));

    expect(getBenchmark).toHaveBeenCalledWith("e1");
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /nsl-kdd/ })).toBeInTheDocument(),
    );
    expect(screen.getByText(/67343 benign used for the fit/)).toBeInTheDocument();
  });
});
