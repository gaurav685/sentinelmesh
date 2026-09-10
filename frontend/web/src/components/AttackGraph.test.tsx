import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { GraphEdge, GraphNode } from "@sentinelmesh/contracts";

const { cyFactory, handlers, lastConfig } = vi.hoisted(() => {
  const handlers: Record<string, (evt: unknown) => void> = {};
  const lastConfig: { value: unknown } = { value: null };
  const cy = {
    on: (event: string, selectorOrFn: unknown, maybeFn?: unknown) => {
      const fn = (typeof selectorOrFn === "function" ? selectorOrFn : maybeFn) as (
        e: unknown,
      ) => void;
      handlers[typeof selectorOrFn === "string" ? `${event}:${selectorOrFn}` : event] = fn;
    },
    nodes: () => ({ removeClass: () => undefined }),
    getElementById: () => ({ addClass: () => undefined }),
    destroy: vi.fn(),
  };
  const cyFactory = vi.fn((config: unknown) => {
    lastConfig.value = config;
    return cy;
  });
  return { cyFactory, handlers, lastConfig };
});

vi.mock("cytoscape", () => ({ default: cyFactory }));

import { AttackGraph } from "./AttackGraph";

const NODES: GraphNode[] = [
  { id: "id-1", labels: ["Identity"], properties: { name: "svc-backup" } },
  { id: "h-1", labels: ["Host"], properties: { name: "web01" } },
];
const EDGES: GraphEdge[] = [
  { src: "id-1", dst: "h-1", type: "AUTHENTICATED_TO", properties: {} },
  { src: "id-1", dst: "missing", type: "TOUCHED", properties: {} },
];

afterEach(() => vi.clearAllMocks());

describe("AttackGraph", () => {
  it("builds cytoscape elements from the contract nodes and edges, dropping dangling edges", async () => {
    render(<AttackGraph nodes={NODES} edges={EDGES} onSelect={vi.fn()} />);
    await waitFor(() => expect(cyFactory).toHaveBeenCalled());

    const config = lastConfig.value as { elements: { data: Record<string, unknown> }[] };
    const ids = config.elements.map((e) => e.data.id);
    expect(ids).toContain("id-1");
    expect(ids).toContain("h-1");
    // the edge to "missing" (a node not in the view) is not rendered
    const edgeEls = config.elements.filter((e) => "source" in e.data);
    expect(edgeEls).toHaveLength(1);
    expect(edgeEls[0]?.data.source).toBe("id-1");
  });

  it("calls onSelect with the tapped node's identity and properties", async () => {
    const onSelect = vi.fn();
    render(<AttackGraph nodes={NODES} edges={EDGES} onSelect={onSelect} />);
    await waitFor(() => expect(handlers["tap:node"]).toBeTypeOf("function"));

    handlers["tap:node"]?.({ target: { data: () => NODES[0] } });
    expect(onSelect).toHaveBeenCalledWith({
      kind: "node",
      id: "id-1",
      labels: ["Identity"],
      properties: { name: "svc-backup" },
    });
  });

  it("shows a text fallback when cytoscape fails to initialise", async () => {
    cyFactory.mockImplementationOnce(() => {
      throw new Error("no canvas");
    });
    render(<AttackGraph nodes={NODES} edges={EDGES} onSelect={vi.fn()} />);
    expect(await screen.findByText(/could not be initialised/i)).toBeInTheDocument();
  });
});
