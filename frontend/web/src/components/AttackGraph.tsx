"use client";

import { useEffect, useRef, useState } from "react";
import type { Core, ElementDefinition, NodeSingular } from "cytoscape";
import type { GraphEdge, GraphNode } from "@sentinelmesh/contracts";

export interface GraphSelection {
  kind: "node" | "edge";
  id: string;
  labels: string[];
  properties: Record<string, unknown>;
}

/** Pick the most specific label for display / colour. */
function primaryLabel(labels: string[]): string {
  return labels.find((l) => l !== "Entity" && l !== "TenantScoped") ?? labels[0] ?? "Node";
}

const PALETTE: Record<string, string> = {
  Identity: "#c084fc",
  Host: "#60a5fa",
  Process: "#34d399",
  File: "#fbbf24",
  Network: "#f87171",
  AttackChain: "#fb7185",
  AttackTechnique: "#f472b6",
  Detection: "#facc15",
};

function toElements(nodes: GraphNode[], edges: GraphEdge[]): ElementDefinition[] {
  const known = new Set(nodes.map((n) => n.id));
  const nodeEls: ElementDefinition[] = nodes.map((n) => {
    const label = primaryLabel(n.labels ?? []);
    return {
      data: {
        id: n.id,
        label,
        title: String((n.properties ?? {}).name ?? (n.properties ?? {}).key ?? label),
        colour: PALETTE[label] ?? "#94a3b8",
        raw: n,
      },
    };
  });
  const edgeEls: ElementDefinition[] = edges
    .filter((e) => known.has(e.src) && known.has(e.dst))
    .map((e, i) => ({
      data: { id: `e${i}`, source: e.src, target: e.dst, label: e.type, raw: e },
    }));
  return [...nodeEls, ...edgeEls];
}

/**
 * The attack-graph canvas. Cytoscape is loaded lazily (client-only) so it never
 * runs during SSR. The graph is decorative for assistive tech — the real,
 * accessible representation is the node/edge list the parent renders alongside
 * it — so the container is aria-hidden and keyboard users drive the list.
 */
export function AttackGraph({
  nodes,
  edges,
  selectedId,
  onSelect,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedId?: string | null;
  onSelect: (sel: GraphSelection | null) => void;
}) {
  const boxRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<Core | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let disposed = false;
    let cy: Core | null = null;
    void (async () => {
      try {
        const cytoscape = (await import("cytoscape")).default;
        if (disposed || !boxRef.current) return;
        cy = cytoscape({
          container: boxRef.current,
          elements: toElements(nodes, edges),
          layout: { name: "cose", animate: false },
          style: [
            {
              selector: "node",
              style: {
                "background-color": "data(colour)",
                label: "data(title)",
                color: "#e2e8f0",
                "font-size": 10,
                "text-valign": "bottom",
                "text-margin-y": 4,
              },
            },
            {
              selector: "edge",
              style: {
                width: 1.5,
                "line-color": "#475569",
                "target-arrow-color": "#475569",
                "target-arrow-shape": "triangle",
                "curve-style": "bezier",
                label: "data(label)",
                "font-size": 8,
                color: "#94a3b8",
              },
            },
            { selector: ".selected", style: { "border-width": 3, "border-color": "#f8fafc" } },
          ],
        });
        cyRef.current = cy;
        cy.on("tap", "node", (evt) => {
          const n = evt.target as NodeSingular;
          const raw = n.data("raw") as GraphNode;
          onSelectRef.current({
            kind: "node",
            id: raw.id,
            labels: raw.labels ?? [],
            properties: (raw.properties ?? {}) as Record<string, unknown>,
          });
        });
        cy.on("tap", (evt) => {
          if (evt.target === cy) onSelectRef.current(null);
        });
      } catch {
        if (!disposed) setFailed(true);
      }
    })();
    return () => {
      disposed = true;
      cy?.destroy();
      cyRef.current = null;
    };
  }, [nodes, edges]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.nodes().removeClass("selected");
    if (selectedId) cy.getElementById(selectedId).addClass("selected");
  }, [selectedId]);

  if (failed) {
    return (
      <p className="state__hint">
        The graph canvas could not be initialised in this browser. The node and edge
        lists below show the same data.
      </p>
    );
  }

  return (
    <div
      ref={boxRef}
      className="attack-graph"
      aria-hidden
      style={{ height: 480, width: "100%", background: "#0b1220", borderRadius: 8 }}
    />
  );
}
