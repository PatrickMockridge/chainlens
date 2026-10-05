/**
 * The canvas: the paths that are logic rather than layout.
 *
 * **What is not tested here, and why.** React Flow renders only what is inside its viewport when
 * `onlyRenderVisibleElements` is on — which it is, deliberately, because that is what keeps a
 * few-hundred-node graph smooth. jsdom performs no layout, so its viewport is zero-sized, so the
 * canvas legitimately draws no nodes. An assertion about node rendering here would fail for a
 * reason that has nothing to do with the app being wrong.
 *
 * What is asserted is what does not depend on layout: that a graph past the ceiling is refused with
 * the count rather than attempted, and that a layout of a real document resolves instead of leaving
 * the app stuck on its loading state. The node semantics — which is where the meaning is — are
 * tested directly in `nodes.test.tsx`.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import type { LedgerDocument } from "../schema/documents";
import { GraphView } from "./GraphView";
import { LAYOUT_LIMIT } from "./layout";

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(
  readFileSync(join(here, "..", "..", "..", "tests", "ledger", "fixtures", "graph-document.json"), "utf8"),
) as { ledgers: Record<string, LedgerDocument> };

const document = fixtures.ledgers["bitcoin"]!;

function draw(nodes: LedgerDocument["nodes"], edges: LedgerDocument["edges"]) {
  return render(
    <GraphView
      nodes={nodes}
      edges={edges}
      highlighted={new Set()}
      withEvidence={new Set()}
      onSelect={() => undefined}
    />,
  );
}

describe("the canvas", () => {
  it("refuses a graph past its ceiling instead of hanging", async () => {
    const many = Array.from({ length: LAYOUT_LIMIT + 100 }, (_, index) => ({
      ...document.nodes[0]!,
      key: `address:bitcoin:fake${index}`,
    }));
    draw(many, []);

    await waitFor(() => expect(screen.getByText(/Not drawing this graph/)).toBeInTheDocument());
    // The count is in the refusal, because "too big" without a number is not actionable.
    expect(screen.getByText(new RegExp(String(many.length)))).toBeInTheDocument();
    expect(screen.getByText(new RegExp(String(LAYOUT_LIMIT)))).toBeInTheDocument();
  });

  it("lays out a real document rather than staying on its loading state", async () => {
    draw(document.nodes, document.edges);
    const loading = screen.getByText(/Laying out/);
    expect(loading).toBeInTheDocument();

    // Resolves to the canvas. Nothing is *drawn* in jsdom — see the module docstring — so the
    // assertion is that the layout finished and the app moved on.
    await waitFor(() => expect(screen.queryByText(/Laying out/)).toBeNull(), { timeout: 30_000 });
    expect(screen.queryByText(/Not drawing/)).toBeNull();
  });
});
