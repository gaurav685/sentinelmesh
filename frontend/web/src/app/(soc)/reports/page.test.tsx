import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const { createReport, getReport } = vi.hoisted(() => ({
  createReport: vi.fn(),
  getReport: vi.fn(),
}));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: { createReport, getReport },
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ csrfToken: "csrf-1" }) }));

import ReportsPage from "./page";

afterEach(() => vi.clearAllMocks());

const REPORT = {
  id: "r1", tenant_id: "t1", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  kind: "incident", status: "partial", subject_type: "host", subject_id: "web01",
  title: "Host incident", requested_by: "u1", generated_at: "2026-01-01T00:00:00Z",
  incident_metadata: {}, timeline: [], affected_assets: [], detection_ids: [],
  evidence: [{ text: "A detection fired.", tier: "evidence", ref: "d1" }],
  chain_ids: [], technique_ids: [], threat_score: null, findings: [], recommendations: [],
  confidence: null, provenance: ["detection-engine"], missing_sections: ["affected_assets"],
  storage_key: null,
};

describe("ReportsPage", () => {
  it("generates a report and shows it in the session library", async () => {
    createReport.mockResolvedValue(REPORT);
    render(<ReportsPage />);

    await userEvent.type(screen.getByPlaceholderText("web01"), "web01");
    await userEvent.type(screen.getByPlaceholderText("Host incident"), "Host incident");
    await userEvent.click(screen.getByRole("button", { name: "Generate" }));

    expect(createReport).toHaveBeenCalledWith(
      { kind: "incident", subject_type: "host", subject_id: "web01", title: "Host incident" },
      "csrf-1",
    );
    await waitFor(() => expect(screen.getAllByText("Host incident").length).toBeGreaterThan(0));
    expect(screen.getByRole("heading", { name: "Evidence" })).toBeInTheDocument();
    expect(screen.getByText("A detection fired.", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("affected_assets", { exact: false })).toBeInTheDocument();
  });

  it("looks up a report by id and shows the download link", async () => {
    getReport.mockResolvedValue({ report: REPORT, download_url: "https://minio.example/x.pdf" });
    render(<ReportsPage />);

    await userEvent.type(screen.getByPlaceholderText("report uuid"), "r1");
    await userEvent.click(screen.getByRole("button", { name: "Look up" }));

    expect(getReport).toHaveBeenCalledWith("r1");
    await waitFor(() => expect(screen.getByRole("link", { name: /Download PDF/ })).toBeInTheDocument());
  });

  it("shows a note when the report has no PDF yet", async () => {
    getReport.mockResolvedValue({ report: { ...REPORT, status: "pending" }, download_url: null });
    render(<ReportsPage />);

    await userEvent.type(screen.getByPlaceholderText("report uuid"), "r1");
    await userEvent.click(screen.getByRole("button", { name: "Look up" }));

    await waitFor(() => expect(screen.getByText("No PDF yet", { exact: false })).toBeInTheDocument());
  });
});
