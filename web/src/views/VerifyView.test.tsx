/**
 * The Verify view: the argument, and the join to the evidence under it.
 *
 * Driven by the committed fixture, which is **real engine output**: the derivations in it were
 * built by `tests/ledger/fixtures.py` from `Post`/`Extraction` objects through
 * `VerificationEngine` and `derive_finding`, not written by hand. The plan's M7 acceptance wording
 * — "fixtures derived from a real `case-study/claims/*.toml` record" — is unreachable, because
 * `case-study/claims/` holds no records yet; these derivations are the substitute, and between them
 * they cover the same two shapes a real one would.
 *
 * Both shapes are asserted because the no-ratio one is the *normal* case today: until a
 * `CoincidenceEstimator` is built, most findings have no ratio, and a view that only looked right
 * when one existed would read as broken rather than as informative.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";

import type { DerivationDocument, LedgerDocument, OverlayDocument } from "../schema/documents";
import { asTree } from "../schema/documents";
import { walkTree } from "../derive/tree";
import {
  addDerivation,
  addLedger,
  emptyStore,
  select,
  selectBranch,
  type Store,
} from "../store";
import { VerifyView } from "./VerifyView";

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(
  readFileSync(join(here, "..", "..", "..", "tests", "ledger", "fixtures", "graph-document.json"), "utf8"),
) as {
  ledgers: Record<string, LedgerDocument>;
  overlays: Record<string, OverlayDocument>;
  derivations: Record<string, DerivationDocument>;
};

const bitcoin = fixtures.ledgers["bitcoin"]!;
const noRatio = fixtures.derivations["no_ratio"]!;
const withRatio = fixtures.derivations["with_ratio"]!;

/** The graph and one derivation, as a reader who dropped both files would have them. */
function loaded(derivation: DerivationDocument, withGraph = true): Store {
  const base = withGraph ? addLedger(emptyStore, "bitcoin.json", bitcoin) : emptyStore;
  return addDerivation(base, derivation);
}

function draw(
  store: Store,
  handlers: { onSelectBranch?: (id: string | null) => void; onSelect?: (key: string) => void } = {},
) {
  return render(
    <VerifyView
      store={store}
      nodes={[...store.nodes.values()]}
      edges={[...store.edges.values()]}
      withEvidence={new Set()}
      onSelect={(selection) => handlers.onSelect?.(selection?.key ?? "")}
      onSelectBranch={handlers.onSelectBranch ?? (() => undefined)}
      onSelectClaim={() => undefined}
    />,
  );
}

/** The step element for a derivation id, so assertions can name the step rather than its words. */
function step(container: HTMLElement, id: string): HTMLElement {
  const found = container.querySelector<HTMLElement>(`[data-branch="${id}"]`);
  if (found === null) throw new Error(`no step rendered for ${id}`);
  return found;
}

/**
 * The step that rests on the transfer edge, found by what it rests on rather than by its id.
 *
 * The builder's ids carry a list index (`…/evidence/transfer/0`), so a hardcoded id would pin
 * these tests to a spelling rather than to the relation they are about.
 */
const TRANSFER_STEP = (() => {
  const found = walkTree(asTree(noRatio.root)).find((node) =>
    (node.graph_refs ?? []).some((ref) => ref.key === "tx1:out:0"),
  );
  if (found === undefined) throw new Error("the fixture derivation rests on no transfer edge");
  return found.id;
})();

describe("the verify view", () => {
  it("says what to load rather than showing an empty argument", () => {
    draw(emptyStore);
    expect(screen.getByText("No derivation loaded")).toBeInTheDocument();
    // Where a derivation comes from, named concretely — "not loaded" without that is a dead end.
    expect(screen.getByText("ledger/derive.py")).toBeInTheDocument();
  });

  it("shows the verdict, the method and the quoted span being adjudicated", () => {
    const { container } = draw(loaded(noRatio));
    // The heading reads "supported transfer": the categorical finding and which checker produced
    // it, together, because the method is part of what the verdict means.
    expect(screen.getByRole("heading", { level: 2, name: /supported transfer/ })).toBeInTheDocument();
    // Verbatim, compared as text rather than through a matcher, because the quote and the
    // limitations both wrap across lines and a normalising matcher would compare unequal to the
    // string it is supposedly checking.
    expect(container.querySelector(".claim-quote")!.textContent).toBe(noRatio.claim_quote);
  });

  it("renders the no-ratio shape without the competing propositions", () => {
    const { container } = draw(loaded(noRatio));
    // The structural claim: with no ratio there are no competing propositions, so drawing a
    // first/alternative pair above an empty ratio node would be the "looks broken" failure.
    expect(screen.queryByText("proposition")).toBeNull();
    expect(container.querySelector(".tree-verdict")).not.toBeNull();
    expect(container.querySelector(".tree-because")).not.toBeNull();
    // And the reason is the engine's own wording, not a summary of it. It appears twice on the
    // step — as the label and as the `reason` detail — which is the point: the detail is the field
    // it was read from, so the two cannot drift apart.
    expect(screen.getAllByText(/no coincidence estimator is configured/).length).toBeGreaterThan(1);
  });

  it("renders the with-ratio shape with the envelope inside the ratio and the band inside that", () => {
    const { container } = draw(loaded(withRatio));
    expect(container.querySelector(".tree-proposition")).not.toBeNull();
    const ratio = container.querySelector(".tree-likelihood_ratio");
    expect(ratio).not.toBeNull();
    // Nesting, asserted structurally, because it is an argument about reading order: the reader
    // meets the qualification before the conclusion, not beside it.
    expect(ratio!.querySelector(".tree-sensitivity")).not.toBeNull();
    expect(container.querySelector(".tree-sensitivity")!.querySelector(".tree-verbal_band")).not.toBeNull();
  });

  it("carries the limitations text verbatim, above the tree", () => {
    const { container } = draw(loaded(noRatio));
    const limitations = container.querySelector(".limitations")!;
    // Verbatim and complete: not summarised, not truncated, not reflowed.
    expect(limitations.textContent).toBe(noRatio.limitations);
    const tree = container.querySelector(".tree")!;
    // Above, not beside or behind a disclosure: a ratio shown without its caveats is the artifact
    // this library is arranged to prevent.
    expect(
      limitations.compareDocumentPosition(tree) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});

describe("opening a step", () => {
  it("hands the click to the store, which is what the other pane reads", () => {
    // A local `useState` here would leave the graph unmarked: the highlight set is derived from
    // the store, so a click that stops inside this component never reaches the canvas.
    const onSelectBranch = vi.fn();
    const { container } = draw(loaded(noRatio), { onSelectBranch });
    fireEvent.click(step(container, TRANSFER_STEP).querySelector(".tree-label")!);
    expect(onSelectBranch).toHaveBeenCalledWith(TRANSFER_STEP);
  });

  it("closes the step when it is the one already open", () => {
    const onSelectBranch = vi.fn();
    const { container } = draw(selectBranch(loaded(noRatio), TRANSFER_STEP), { onSelectBranch });
    const opened = step(container, TRANSFER_STEP);
    expect(opened.className).toContain("selected");
    fireEvent.click(opened.querySelector(".tree-label")!);
    // A selection with no way back is a trap.
    expect(onSelectBranch).toHaveBeenCalledWith(null);
  });

  it("reports how much of the graph the opened step highlights", () => {
    draw(selectBranch(loaded(noRatio), TRANSFER_STEP));
    expect(screen.getByText(/Highlighting/)).toBeInTheDocument();
  });

  it("emphasises the steps resting on what the graph has selected", () => {
    const store = select(loaded(noRatio), { kind: "node", key: "transaction:bitcoin:tx1" });
    const { container } = draw(store);
    expect(
      screen.getByText(/step\(s\) of this argument rest on what you selected/),
    ).toBeInTheDocument();
    expect(container.querySelectorAll(".tree-node.highlighted").length).toBeGreaterThan(0);
  });

  it("says nothing is selected when nothing is, rather than showing an empty highlight", () => {
    draw(loaded(noRatio));
    expect(screen.getByText(/Click a step to highlight/)).toBeInTheDocument();
  });

  it("says both things when both are true", () => {
    // A step can be open while a graph node is selected, and both statements remain facts. Showing
    // one by hiding the other would be the same failure as an unstated caveat.
    const store = select(selectBranch(loaded(noRatio), TRANSFER_STEP), {
      kind: "node",
      key: "transaction:bitcoin:tx1",
    });
    draw(store);
    expect(screen.getByText(/Highlighting/)).toBeInTheDocument();
    expect(screen.getByText(/step\(s\) of this argument rest on/)).toBeInTheDocument();
  });

  it("selects a reference back in the graph when a chip is clicked", () => {
    const onSelect = vi.fn();
    const { container } = draw(loaded(noRatio), { onSelect });
    const chip = within(step(container, TRANSFER_STEP)).getByRole("button", { name: "tx1:out:0" });
    fireEvent.click(chip);
    expect(onSelect).toHaveBeenCalledWith("tx1:out:0");
  });
});

describe("references the graph does not hold", () => {
  it("counts them on the step that rests on them, rather than dropping them", () => {
    const { container } = draw(loaded(noRatio, false));
    expect(screen.getAllByText(/not in the loaded view/).length).toBeGreaterThan(0);
    expect(container.querySelectorAll(".ref-chip.ref-absent").length).toBeGreaterThan(0);
  });

  it("marks no reference absent when the graph holds them all", () => {
    const { container } = draw(loaded(noRatio));
    expect(container.querySelectorAll(".ref-chip.ref-absent").length).toBe(0);
    expect(screen.queryByText(/not in the loaded view/)).toBeNull();
  });

  it("explains an empty canvas rather than leaving it blank", () => {
    // The tree still renders without the graph — deliberately, because the argument is readable on
    // its own and every reference says it is not in the view.
    draw(loaded(withRatio, false));
    expect(screen.getByText("No graph loaded")).toBeInTheDocument();
    expect(screen.queryByText(/Not drawing/)).toBeNull();
  });
});

describe("the claim selector", () => {
  it("offers each loaded claim when there is more than one", () => {
    // Two derivations cannot share a claim id — `addDerivation` dedupes on it — so this is the
    // shape a reader gets from two different findings.
    const other: DerivationDocument = { ...noRatio, claim_id: "claim:other", verdict: "contradicted" };
    draw(addDerivation(loaded(noRatio), other));
    expect(screen.getByText("Claims in this view")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /contradicted/ })).toBeInTheDocument();
  });

  it("does not show the selector for a single claim", () => {
    draw(loaded(noRatio));
    expect(screen.queryByText("Claims in this view")).toBeNull();
  });
});
