import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const { decoys, registerDecoy, teardownDecoy, decoyInteractions } = vi.hoisted(() => ({
  decoys: vi.fn(),
  registerDecoy: vi.fn(),
  teardownDecoy: vi.fn(),
  decoyInteractions: vi.fn(),
}));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: { decoys, registerDecoy, teardownDecoy, decoyInteractions },
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ csrfToken: "csrf-1" }) }));

import DeceptionPage from "./page";

afterEach(() => vi.clearAllMocks());

const DECOY = {
  id: "d1", tenant_id: "t1", name: "ssh-honeypot", kind: "honeypot_host",
  network_boundary: "isolated", status: "active", ttl_seconds: 3600,
  tags: [], created_at: "2026-01-01T00:00:00Z",
};

describe("DeceptionPage", () => {
  it("shows an empty state with no decoys registered", async () => {
    decoys.mockResolvedValue([]);
    render(<DeceptionPage />);
    await waitFor(() => expect(screen.getByText("No decoys registered")).toBeInTheDocument());
  });

  it("registers a decoy and refreshes the list", async () => {
    decoys.mockResolvedValueOnce([]).mockResolvedValueOnce([DECOY]);
    registerDecoy.mockResolvedValue(DECOY);
    render(<DeceptionPage />);
    await waitFor(() => expect(screen.getByText("No decoys registered")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Register decoy" }));
    expect(registerDecoy).toHaveBeenCalledWith(
      { name: "ssh-honeypot", kind: "honeypot_host", network_boundary: "isolated" },
      "csrf-1",
    );
    await waitFor(() => expect(screen.getByText("ssh-honeypot")).toBeInTheDocument());
  });

  it("does not offer 'production' as a network boundary option", async () => {
    decoys.mockResolvedValue([]);
    render(<DeceptionPage />);
    await waitFor(() => expect(screen.getByText("No decoys registered")).toBeInTheDocument());
    const options = screen.getAllByRole("option").map((o) => o.textContent);
    expect(options).not.toContain("production");
  });

  it("shows captured interactions for a selected decoy", async () => {
    decoys.mockResolvedValue([DECOY]);
    decoyInteractions.mockResolvedValue([
      { id: "i1", decoy_id: "d1", tenant_id: "t1", source: "10.0.0.9", captured_at: "2026-01-01T00:00:00Z" },
    ]);
    render(<DeceptionPage />);
    await waitFor(() => expect(screen.getByText("ssh-honeypot")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Interactions" }));
    await waitFor(() => expect(screen.getByText("10.0.0.9")).toBeInTheDocument());
  });

  it("tears down a decoy", async () => {
    decoys.mockResolvedValueOnce([DECOY]).mockResolvedValueOnce([{ ...DECOY, status: "torn_down" }]);
    teardownDecoy.mockResolvedValue({ ...DECOY, status: "torn_down" });
    render(<DeceptionPage />);
    await waitFor(() => expect(screen.getByText("ssh-honeypot")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Tear down" }));
    expect(teardownDecoy).toHaveBeenCalledWith("d1", "csrf-1");
    await waitFor(() => expect(screen.getByText("torn_down")).toBeInTheDocument());
  });
});
