/**
 * The panel: the target an assertion would have, and the offer to walk on.
 *
 * Two things here are the difference between a record and a remark, and between a boundary and an
 * ending. A form that let a reader type the key would let a typo place evidence on a different
 * address — the most damaging mistake this panel could make and the one nobody would notice,
 * because the record would look exactly like a correct one. And a walk that stopped at an address
 * has to say so and offer to continue, because a graph that showed the stop as the edge of the
 * world would be describing the walk's budget as the chain's shape.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";

import type { AnnotationRequest, LedgerDocument } from "../schema/documents";
import { addLedger, emptyStore, select, type Store } from "../store";
import { EvidencePanel, expandable } from "./EvidencePanel";

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(
  readFileSync(join(here, "..", "..", "..", "tests", "ledger", "fixtures", "graph-document.json"), "utf8"),
) as { ledgers: Record<string, LedgerDocument> };

const bitcoin = fixtures.ledgers["bitcoin"]!;
const frontierLedger = fixtures.ledgers["frontier"]!;
const EDGE = bitcoin.edges.find((edge) => edge.role === "output")!.key;
const NODE = bitcoin.nodes.find((node) => node.kind === "address")!.key;
const ABSENT = "address:bitcoin:1CounterpartyXXXXXXXXXXXXXXXUWLpVr";

type OnRecord = (request: AnnotationRequest) => Promise<string | null>;
type OnExpand = (key: string) => Promise<string | null>;

function renderPanel(
  store: Store,
  props: Partial<Parameters<typeof EvidencePanel>[0]> = {},
) {
  const onRecord = vi.fn<OnRecord>(async () => null);
  const onExpand = vi.fn<OnExpand>(async () => null);
  render(
    <EvidencePanel
      store={store}
      evidence={[]}
      missing={[]}
      write={{ writable: true, reason: null }}
      onRecord={onRecord}
      live
      onExpand={onExpand}
      onSelectClaim={() => undefined}
      onSelectBranch={() => undefined}
      onSelectRef={() => undefined}
      {...props}
    />,
  );
  return { onRecord, onExpand };
}

function ledger(document: LedgerDocument, selection?: Store["selection"]): Store {
  const store = addLedger(emptyStore, "bitcoin.json", document);
  return selection === undefined || selection === null ? store : select(store, selection);
}

function fillAndSubmit() {
  fireEvent.change(screen.getByLabelText("assertion"), { target: { value: "a venue deposit" } });
  fireEvent.change(screen.getByLabelText("author"), { target: { value: "pm" } });
  fireEvent.change(screen.getByLabelText("basis"), { target: { value: "listed by the venue" } });
  fireEvent.click(screen.getByRole("button", { name: "Record it" }));
}

describe("authoring from the panel", () => {
  it("offers nothing when nothing is selected", () => {
    renderPanel(ledger(bitcoin));
    expect(screen.queryByText("Record an assertion")).toBeNull();
  });

  it("takes the selected edge as the target, and says it is an edge", async () => {
    const { onRecord } = renderPanel(ledger(bitcoin, { kind: "edge", key: EDGE }));
    fillAndSubmit();

    await waitFor(() => expect(onRecord).toHaveBeenCalledTimes(1));
    expect(onRecord.mock.calls[0]![0].target).toEqual({
      kind: "edge",
      key: EDGE,
      exists: null,
      note: null,
    });
  });

  it("takes the selected address as the target, and says it is a node", async () => {
    const { onRecord } = renderPanel(ledger(bitcoin, { kind: "node", key: NODE }));
    fillAndSubmit();

    await waitFor(() => expect(onRecord).toHaveBeenCalledTimes(1));
    expect(onRecord.mock.calls[0]![0].target).toEqual({
      kind: "node",
      key: NODE,
      exists: null,
      note: null,
    });
  });

  it("offers no field that could change the target", () => {
    // The key is shown in the panel's own heading, which is not an input; nothing in the form
    // holds it, so there is no way to record an assertion about something else.
    const { container } = render(
      <EvidencePanel
        store={ledger(bitcoin, { kind: "node", key: NODE })}
        evidence={[]}
        missing={[]}
        write={{ writable: true, reason: null }}
        onRecord={vi.fn<OnRecord>(async () => null)}
        live
        onExpand={vi.fn<OnExpand>(async () => null)}
        onSelectClaim={() => undefined}
        onSelectBranch={() => undefined}
        onSelectRef={() => undefined}
      />,
    );
    for (const field of container.querySelector(".annotate")!.querySelectorAll("input, textarea, select")) {
      expect((field as HTMLInputElement).value).not.toBe(NODE);
    }
  });

  it("says why it cannot record when the server will not write", () => {
    renderPanel(ledger(bitcoin, { kind: "node", key: NODE }), {
      write: { writable: false, reason: "the server was started without an annotation directory" },
    });
    expect(screen.getByText(/without an annotation directory/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record it" })).toBeNull();
  });
});

describe("walking on from a node", () => {
  it("offers to continue from a frontier address, and says the walk stopped there", () => {
    const frontier = frontierLedger.frontier ?? [];
    expect(frontier.length).toBeGreaterThan(0);
    renderPanel(ledger(frontierLedger, { kind: "node", key: frontier[0]! }));
    expect(screen.getByText(/walk stopped at this address/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Walk one level out" })).toBeInTheDocument();
  });

  it("hands the key to the app rather than expanding it itself", async () => {
    const key = (frontierLedger.frontier ?? [])[0]!;
    const { onExpand } = renderPanel(ledger(frontierLedger, { kind: "node", key }));
    fireEvent.click(screen.getByRole("button", { name: "Walk one level out" }));
    await waitFor(() => expect(onExpand).toHaveBeenCalledWith(key));
  });

  it("offers to fetch an address this graph does not hold at all", () => {
    renderPanel(ledger(bitcoin, { kind: "node", key: ABSENT }));
    // A different message from the frontier's, because it is a different situation: referred to
    // and not here, rather than known about and not looked into.
    expect(screen.getByText(/It is referred to rather than absent/)).toBeInTheDocument();
  });

  it("shows the server's refusal rather than failing quietly", async () => {
    const key = (frontierLedger.frontier ?? [])[0]!;
    const onExpand = vi.fn<OnExpand>(async () => "the walk did not complete: provider unavailable");
    renderPanel(ledger(frontierLedger, { kind: "node", key }), { onExpand });
    fireEvent.click(screen.getByRole("button", { name: "Walk one level out" }));
    expect(await screen.findByText(/provider unavailable/)).toBeInTheDocument();
  });

  it("offers nothing in static mode, because there is nothing to ask", () => {
    const key = (frontierLedger.frontier ?? [])[0]!;
    renderPanel(ledger(frontierLedger, { kind: "node", key }), { live: false });
    expect(screen.queryByRole("button", { name: "Walk one level out" })).toBeNull();
  });

  it("never offers to expand a transaction, whose neighbours are already drawn", () => {
    const txid = bitcoin.nodes.find((node) => node.kind === "transaction")!.key;
    const store = ledger(bitcoin, { kind: "node", key: txid });
    expect(expandable(store, txid, true)).toBe(false);
    renderPanel(store);
    expect(screen.queryByRole("button", { name: "Walk one level out" })).toBeNull();
  });

  it("does not offer to expand an address whose history is already in front of the reader", () => {
    // A drawn, non-frontier address was expanded: the same walk would return the same document,
    // so the button would be an invitation to do nothing.
    const store = ledger(bitcoin, { kind: "node", key: NODE });
    expect(store.frontier.has(NODE)).toBe(false);
    expect(expandable(store, NODE, true)).toBe(false);
  });
});
