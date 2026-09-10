import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const { hunt } = vi.hoisted(() => ({ hunt: vi.fn() }));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: { hunt } }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ csrfToken: "csrf-1" }) }));

import HuntPage from "./page";

afterEach(() => vi.clearAllMocks());

const _PLAN = {
  intent: "list_related",
  selectors: [{ type: "host", value: "web01" }],
  rel_types: [],
  limits: { max_depth: 2, max_rows: 100 },
};

describe("HuntPage", () => {
  it("sends a natural-language question and renders the result + the compiled plan", async () => {
    hunt.mockResolvedValue({
      supported: true,
      unsupported_reason: "",
      history_id: "h1",
      result: {
        intent: "list_related",
        plan: _PLAN,
        rows: [{ id: "n1", labels: ["IpAddress"], properties: { ip: "10.0.0.9" } }],
        row_count: 1,
        truncated: false,
        cypher_fingerprint: "fp123456789abc",
        explanation: "web01 talks to one ip [rows].",
      },
    });
    render(<HuntPage />);
    await userEvent.type(screen.getByLabelText("Question"), "what talks to web01");
    await userEvent.click(screen.getByRole("button", { name: "Run hunt" }));

    expect(hunt).toHaveBeenCalledWith({ query: "what talks to web01" }, "csrf-1");
    await waitFor(() => expect(screen.getByText(/web01 talks to one ip/)).toBeInTheDocument());
    expect(screen.getByText("Compiled query plan")).toBeInTheDocument();
    expect(screen.getByText(/10\.0\.0\.9/)).toBeInTheDocument();
  });

  it("shows the reason when the query cannot be planned, and does not pretend to have run it", async () => {
    hunt.mockResolvedValue({
      supported: false,
      unsupported_reason: "not a threat-hunting question",
      result: null,
    });
    render(<HuntPage />);
    await userEvent.type(screen.getByLabelText("Question"), "tell me a joke");
    await userEvent.click(screen.getByRole("button", { name: "Run hunt" }));
    await waitFor(() =>
      expect(screen.getByText("not a threat-hunting question")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Rows")).not.toBeInTheDocument();
  });

  it("builds a structured QueryPlan in quick mode without an LLM", async () => {
    hunt.mockResolvedValue({
      supported: true,
      unsupported_reason: "",
      result: {
        intent: "find_entity",
        plan: _PLAN,
        rows: [],
        row_count: 0,
        truncated: false,
        cypher_fingerprint: "fp",
        explanation: "",
      },
    });
    render(<HuntPage />);
    await userEvent.click(screen.getByRole("button", { name: "Quick query" }));
    await userEvent.selectOptions(screen.getByLabelText("Intent"), "find_entity");
    await userEvent.selectOptions(screen.getByLabelText("Entity type"), "host");
    await userEvent.type(screen.getByLabelText("Value"), "web01");
    await userEvent.click(screen.getByRole("button", { name: "Run hunt" }));

    expect(hunt).toHaveBeenCalledWith(
      {
        plan: {
          intent: "find_entity",
          selectors: [{ type: "host", value: "web01" }],
          rel_types: [],
          limits: { max_depth: 2, max_rows: 100 },
        },
      },
      "csrf-1",
    );
    await waitFor(() =>
      expect(screen.getByText(/nothing has been observed/)).toBeInTheDocument(),
    );
  });
});
