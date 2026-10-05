/**
 * The panel, and the one thing it must get right about authoring: the target.
 *
 * A form that let a reader type the key would let a typo place evidence on a different address —
 * the most damaging mistake this panel could make and the one nobody would notice, because the
 * record would look exactly like a correct one. So the target is asserted to be the selection, for
 * both a node and an edge, with the right `kind` for each.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";

import type { AnnotationRequest, LedgerDocument } from "../schema/documents";
import { addLedger, emptyStore, select, type Store } from "../store";
import { EvidencePanel } from "./EvidencePanel";

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(
  readFileSync(join(here, "..", "..", "..", "tests", "ledger", "fixtures", "graph-document.json"), "utf8"),
) as { ledgers: Record<string, LedgerDocument> };

const bitcoin = fixtures.ledgers["bitcoin"]!;
const EDGE = bitcoin.edges.find((edge) => edge.role === "output")!.key;
const NODE = bitcoin.nodes.find((node) => node.kind === "address")!.key;

type OnRecord = (request: AnnotationRequest) => Promise<string | null>;

function draw(store: Store) {
  const onRecord = vi.fn<OnRecord>(async () => null);
  render(
    <EvidencePanel
      store={store}
      evidence={[]}
      missing={[]}
      write={{ writable: true, reason: null }}
      onRecord={onRecord}
      onSelectClaim={() => undefined}
      onSelectBranch={() => undefined}
      onSelectRef={() => undefined}
    />,
  );
  return onRecord;
}

function fillAndSubmit() {
  fireEvent.change(screen.getByLabelText("assertion"), { target: { value: "a venue deposit" } });
  fireEvent.change(screen.getByLabelText("author"), { target: { value: "pm" } });
  fireEvent.change(screen.getByLabelText("basis"), { target: { value: "listed by the venue" } });
  fireEvent.click(screen.getByRole("button", { name: "Record it" }));
}

describe("authoring from the panel", () => {
  it("offers nothing when nothing is selected", () => {
    draw(addLedger(emptyStore, "bitcoin.json", bitcoin));
    expect(screen.queryByText("Record an assertion")).toBeNull();
  });

  it("takes the selected edge as the target, and says it is an edge", async () => {
    const onRecord = draw(select(addLedger(emptyStore, "bitcoin.json", bitcoin), { kind: "edge", key: EDGE }));
    fillAndSubmit();

    await waitFor(() => expect(onRecord).toHaveBeenCalledTimes(1));
    expect(onRecord.mock.calls[0]![0].target).toEqual({ kind: "edge", key: EDGE, exists: null, note: null });
  });

  it("takes the selected address as the target, and says it is a node", async () => {
    const onRecord = draw(select(addLedger(emptyStore, "bitcoin.json", bitcoin), { kind: "node", key: NODE }));
    fillAndSubmit();

    await waitFor(() => expect(onRecord).toHaveBeenCalledTimes(1));
    expect(onRecord.mock.calls[0]![0].target).toEqual({ kind: "node", key: NODE, exists: null, note: null });
  });

  it("offers no field that could change the target", () => {
    // The nearest thing to a guard: the key appears nowhere in the form as a value a reader could
    // edit. It is shown in the panel's own heading, which is not an input.
    const store = select(addLedger(emptyStore, "bitcoin.json", bitcoin), { kind: "node", key: NODE });
    const { container } = render(
      <EvidencePanel
        store={store}
        evidence={[]}
        missing={[]}
        write={{ writable: true, reason: null }}
        onRecord={vi.fn<OnRecord>(async () => null)}
        onSelectClaim={() => undefined}
        onSelectBranch={() => undefined}
        onSelectRef={() => undefined}
      />,
    );
    const form = container.querySelector(".annotate")!;
    for (const field of form.querySelectorAll("input, textarea, select")) {
      expect((field as HTMLInputElement).value).not.toBe(NODE);
    }
  });

  it("says why it cannot record when the server will not write", () => {
    const store = select(addLedger(emptyStore, "bitcoin.json", bitcoin), { kind: "node", key: NODE });
    render(
      <EvidencePanel
        store={store}
        evidence={[]}
        missing={[]}
        write={{ writable: false, reason: "the server was started without an annotation directory" }}
        onRecord={vi.fn<OnRecord>(async () => null)}
        onSelectClaim={() => undefined}
        onSelectBranch={() => undefined}
        onSelectRef={() => undefined}
      />,
    );
    expect(screen.getByText(/without an annotation directory/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record it" })).toBeNull();
  });
});
