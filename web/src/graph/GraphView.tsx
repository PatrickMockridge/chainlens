/**
 * The canvas: the ledger as a bipartite graph, laid out and drawn.
 *
 * Two things here are not decoration.
 *
 * **`onlyRenderVisibleElements`.** React Flow draws into the DOM, and a graph of a few hundred
 * nodes is the point at which that starts to matter. Off-screen nodes are simply not rendered,
 * which is what keeps panning smooth at the sizes the walk's own ceilings allow.
 *
 * **A size guard that refuses rather than hanging.** Past `LAYOUT_LIMIT` the view draws nothing
 * and says how many nodes there were and what to do about it. A tab that stops responding is a
 * worse answer than a sentence, and the honest alternative — silently drawing part of the graph —
 * would misrepresent it.
 */
import { Background, Controls, ReactFlow, type Edge, type Node } from "@xyflow/react";
import { useEffect, useMemo, useState } from "react";

import type { LedgerEdge, LedgerNode } from "../schema/documents";
import { LAYOUT_LIMIT, layoutGraph } from "./layout";
import { edgeClass, nodeTypes, type NodeData } from "./nodes";

export interface GraphViewProps {
  nodes: readonly LedgerNode[];
  edges: readonly LedgerEdge[];
  /** Keys to emphasise, from a selection in either view. */
  highlighted: ReadonlySet<string>;
  /** Keys carrying evidence, so a node can say so without a click. */
  withEvidence: ReadonlySet<string>;
  onSelect: (selection: { kind: "node" | "edge"; key: string } | null) => void;
}

export function GraphView({ nodes, edges, highlighted, withEvidence, onSelect }: GraphViewProps) {
  const [positions, setPositions] = useState<Map<string, { x: number; y: number }> | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const degrees = useMemo(() => {
    const drawn = new Map<string, { in: number; out: number }>();
    for (const edge of edges) {
      const target = drawn.get(edge.dst) ?? { in: 0, out: 0 };
      target.in += 1;
      drawn.set(edge.dst, target);
      const source = drawn.get(edge.src) ?? { in: 0, out: 0 };
      source.out += 1;
      drawn.set(edge.src, source);
    }
    return drawn;
  }, [edges]);

  // Relayout whenever the node set changes, which is what an expansion does. Keyed on the keys
  // rather than on the array, so a re-render that produced an equal set does not reflow.
  const nodeKeys = useMemo(() => nodes.map((node) => node.key).join("|"), [nodes]);
  useEffect(() => {
    let cancelled = false;
    setFailure(null);
    layoutGraph(nodes, edges)
      .then((placed) => {
        if (!cancelled) setPositions(placed);
      })
      .catch((error: unknown) => {
        if (!cancelled) setFailure(error instanceof Error ? error.message : String(error));
      });
    return () => {
      cancelled = true;
    };
    // `edges` is included because a new edge between existing nodes still changes the layout.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeKeys, edges]);

  if (failure !== null) {
    return (
      <div className="canvas-refusal" role="status">
        <h2>Not drawing this graph</h2>
        <p>{failure}</p>
      </div>
    );
  }

  if (positions === null) {
    return (
      <div className="canvas-loading" role="status">
        Laying out {nodes.length} nodes ({LAYOUT_LIMIT} is the ceiling)…
      </div>
    );
  }

  const flowNodes: Node<NodeData>[] = nodes.map((node) => {
    const counts = degrees.get(node.key) ?? { in: 0, out: 0 };
    return {
      id: node.key,
      type: node.kind,
      position: positions.get(node.key) ?? { x: 0, y: 0 },
      data: {
        node,
        drawnInputs: counts.in,
        drawnOutputs: counts.out,
        hasEvidence: withEvidence.has(node.key),
        highlighted: highlighted.has(node.key),
      },
      selected: highlighted.has(node.key),
    };
  });

  const flowEdges: Edge[] = edges.map((edge) => ({
    id: edge.key,
    source: edge.src,
    target: edge.dst,
    className: edgeClass(edge),
    // No arrowhead: an edge runs from an address into a transaction and out again, and an arrow
    // at every end would suggest a direction the ledger did not record.
    animated: false,
  }));

  return (
    <ReactFlow
      nodes={flowNodes}
      edges={flowEdges}
      nodeTypes={nodeTypes}
      onlyRenderVisibleElements
      fitView
      minZoom={0.05}
      proOptions={{ hideAttribution: false }}
      onNodeClick={(_, node) => onSelect({ kind: "node", key: node.id })}
      onEdgeClick={(_, edge) => onSelect({ kind: "edge", key: edge.id })}
      onPaneClick={() => onSelect(null)}
    >
      <Background />
      <Controls />
    </ReactFlow>
  );
}
