/**
 * Where the nodes go.
 *
 * React Flow draws but does not lay out, and a chain graph is a DAG — address into transaction
 * into address — so a layered left-to-right arrangement is the one that reads. ELK does it.
 *
 * **Sizes are fixed rather than measured.** The usual advice is to render, measure, then lay out,
 * because a node's size depends on its content. Here every node has a fixed width and height by
 * design: a label that overflows is truncated with the full text in the panel, rather than being
 * allowed to reshape the graph. That removes a whole class of layout churn (moving a selection
 * reflowing everything) and makes a layout reproducible from the document alone, which matters
 * because the same graph should look the same tomorrow.
 */
import type { default as ElkConstructor, ElkNode } from "elkjs/lib/elk.bundled.js";

/** The instance type, since the module exports a constructor rather than a type. */
type Elk = InstanceType<typeof ElkConstructor>;

import type { LedgerEdge, LedgerNode } from "../schema/documents";

/** Fixed dimensions, by node kind. Kept here so the components and the layout agree. */
export const NODE_SIZE: Record<string, { width: number; height: number }> = {
  address: { width: 208, height: 52 },
  transaction: { width: 172, height: 56 },
  unparsed: { width: 152, height: 44 },
};

/** Past this many elements the browser stops being interactive, so the app refuses instead. */
export const LAYOUT_LIMIT = 800;

export interface Placement {
  id: string;
  x: number;
  y: number;
}

/**
 * The layout engine, loaded on first use.
 *
 * ELK is by far the largest thing in this bundle — it is a compiled graph-layout engine, and it
 * outweighs React, React Flow and zod together. Importing it dynamically puts it in its own chunk,
 * so the app boots and renders its own chrome without parsing it, and a loaded document that turns
 * out to need no layout never pays for it. The bytes still ship in the wheel; what changes is when
 * they cost anything.
 */
let engine: Promise<Elk> | null = null;

async function elk(): Promise<Elk> {
  engine ??= import("elkjs/lib/elk.bundled.js").then((module) => new module.default());
  return engine;
}

export async function layoutGraph(
  nodes: readonly LedgerNode[],
  edges: readonly LedgerEdge[],
): Promise<Map<string, Placement>> {
  if (nodes.length > LAYOUT_LIMIT) {
    // Refused rather than attempted. The walk's own ceilings keep this from being the normal
    // case, and a tab that stops responding is a worse answer than a sentence.
    throw new Error(
      `${nodes.length} nodes is past the ${LAYOUT_LIMIT} this view will draw at once. ` +
        "Load one export rather than several, or walk a shallower neighbourhood.",
    );
  }

  const graph: ElkNode = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      // The seed is the leftmost layer, and value reads outward from it.
      "elk.layered.spacing.nodeNodeBetweenLayers": "72",
      "elk.spacing.nodeNode": "28",
      // A transaction's fan-out is the case a layered layout handles worst; this keeps the
      // edges from crossing into a knot without widening the graph beyond use.
      "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
      "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
      "elk.edgeRouting": "ORTHOGONAL",
    },
    children: nodes.map((node) => ({
      id: node.key,
      width: NODE_SIZE[node.kind]?.width ?? 180,
      height: NODE_SIZE[node.kind]?.height ?? 52,
    })),
    edges: edges.map((edge) => ({
      id: edge.key,
      sources: [edge.src],
      targets: [edge.dst],
    })),
  };

  const laid = await (await elk()).layout(graph);
  const placed = new Map<string, Placement>();
  for (const child of laid.children ?? []) {
    placed.set(child.id, { id: child.id, x: child.x ?? 0, y: child.y ?? 0 });
  }
  return placed;
}
