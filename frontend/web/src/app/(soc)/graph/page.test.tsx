import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const { graphNeighbors } = vi.hoisted(() => ({ graphNeighbors: vi.fn() }));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: { graphNeighbors },
}));
vi.mock("@/components/AttackGraph", () => ({
  AttackGraph: ({
    onSelect,
  }: {
    onSelect: (s: {
      kind: string;
      id: string;
      labels: string[];
      properties: Record<string, unknown>;
    }) => void;
  }) => (
    <button
      type="button"
      onClick={() =>
        onSelect({ kind: "node", id: "id-1", labels: ["Identity"], properties: { name: "svc-backup" } })
      }
    >
      canvas-pick
    </button>
  ),
}));

import GraphPage from "./page";

afterEach(() => vi.clearAllMocks());

async function explore() {
  await userEvent.type(screen.getByLabelText(/Natural key/), "svc-backup");
  await userEvent.click(screen.getByRole("button", { name: "Explore" }));
}

describe("GraphPage", () => {
  it("queries the BFF and lists the returned nodes and edges", async () => {
    graphNeighbors.mockResolvedValue({
      root_id: "svc-backup",
      depth: 2,
      nodes: [
        { id: "id-1", labels: ["Identity"], properties: { name: "svc-backup" } },
        { id: "h-1", labels: ["Host"], properties: { name: "web01" } },
      ],
      edges: [{ src: "id-1", dst: "h-1", type: "AUTHENTICATED_TO", properties: {} }],
      truncated: false,
    });
    render(<GraphPage />);
    await explore();

    expect(graphNeighbors).toHaveBeenCalledWith(
      { label: "Identity", key: "svc-backup", depth: 2 },
      expect.anything(),
    );
    await waitFor(() => expect(screen.getByText("Nodes (2)")).toBeInTheDocument());
    expect(screen.getByText("Edges (1)")).toBeInTheDocument();
    expect(screen.getByText("AUTHENTICATED_TO")).toBeInTheDocument();
  });

  it("warns when the neighbourhood was truncated by the server cap", async () => {
    graphNeighbors.mockResolvedValue({
      root_id: "svc-backup",
      depth: 2,
      nodes: [{ id: "id-1", labels: ["Identity"], properties: {} }],
      edges: [],
      truncated: true,
    });
    render(<GraphPage />);
    await explore();
    await waitFor(() =>
      expect(screen.getByText(/server row cap was hit/i)).toBeInTheDocument(),
    );
  });

  it("shows the selected node's properties in the detail panel", async () => {
    graphNeighbors.mockResolvedValue({
      root_id: "svc-backup",
      depth: 2,
      nodes: [{ id: "id-1", labels: ["Identity"], properties: { name: "svc-backup" } }],
      edges: [],
      truncated: false,
    });
    render(<GraphPage />);
    await explore();
    await waitFor(() => expect(screen.getByText("canvas-pick")).toBeInTheDocument());
    await userEvent.click(screen.getByText("canvas-pick"));
    // the detail panel shows the node id and its properties
    expect(screen.getByText("id-1")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "svc-backup" })).toBeInTheDocument();
  });

  it("shows an empty state when the node has no graph data", async () => {
    graphNeighbors.mockResolvedValue({
      root_id: "svc-backup",
      depth: 2,
      nodes: [],
      edges: [],
      truncated: false,
    });
    render(<GraphPage />);
    await explore();
    await waitFor(() =>
      expect(screen.getByText("No graph data for this node")).toBeInTheDocument(),
    );
  });
});
