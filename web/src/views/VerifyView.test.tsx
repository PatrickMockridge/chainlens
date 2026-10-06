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

import type {
  DerivationDocument,
  LedgerDocument,
  NarrativeDocument,
  OverlayDocument,
} from "../schema/documents";
import { asTree } from "../schema/documents";
import { posteriorProbability } from "../derive/posterior";
import { detailValue, findRatio, walkTree } from "../derive/tree";
import {
  addDerivation,
  addLedger,
  addNarrative,
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
  narratives: Record<string, NarrativeDocument>;
};

const bitcoin = fixtures.ledgers["bitcoin"]!;
const narrative = fixtures.narratives["with_prose"]!;
const noRatio = fixtures.derivations["no_ratio"]!;
const ratioNoPrior = fixtures.derivations["ratio_without_prior"]!;
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

  it("renders the no-ratio shape as a calculation with a hole, not as a sentence", () => {
    const { container } = draw(loaded(noRatio));
    // The structural claim, in two halves. With no ratio there are still no competing
    // propositions — drawing a first/alternative pair above a number that does not exist would
    // be the "looks broken" failure. But the ratio node *is* drawn, carrying the formula and the
    // input that stopped it, which is the difference between a withheld number and an absent
    // argument.
    expect(screen.queryByText("proposition")).toBeNull();
    expect(container.querySelector(".tree-verdict")).not.toBeNull();
    expect(container.querySelector(".tree-likelihood_ratio")).not.toBeNull();
    expect(container.querySelector(".tree-because")).toBeNull();
    // The formula a reader could check by hand, and the reason nothing was computed from it.
    expect(screen.getByText(/1 \/ \(1 - \(1 - p\) \*\* k\) — not computed/)).toBeInTheDocument();
    // The reason appears twice, and both are load-bearing: once on `p`, which is the input with
    // no value and has to say which kind of missing it is, and once on the operation, which has
    // to say which input stopped it. A reader arriving at either one learns the same thing.
    expect(screen.getAllByText(/no coincidence estimator is configured/).length).toBe(2);
    // And the inputs the formula would have consumed, one of them with no value at all.
    expect(container.querySelectorAll(".tree-quantity_k").length).toBe(1);
    expect(container.querySelectorAll(".tree-quantity_p").length).toBe(1);
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

/**
 * The prior, end to end through the view.
 *
 * The arithmetic is pinned elsewhere; what is asserted here is that the control is wired to the
 * *tree* — that a prior supplied in the browser lands as a step under the ratio, marked as the
 * reader's, with the caveats swapped to match — because that wiring is the whole reason the prior
 * is a view parameter rather than a document field.
 */
describe("the prior, supplied in the browser", () => {
  it("draws nothing until the reader supplies one", () => {
    const { container } = draw(loaded(ratioNoPrior));
    expect(container.querySelectorAll(".tree-node.reader").length).toBe(0);
    // The document's own caveats stand, unswapped.
    expect(container.querySelector(".limitations")!.textContent).toBe(ratioNoPrior.limitations);
    expect(screen.getByRole("button", { name: "Supply a prior" })).toBeInTheDocument();
  });

  it("attaches the posterior beneath the ratio, marked as the reader's", () => {
    const { container } = draw(loaded(ratioNoPrior));
    fireEvent.click(screen.getByRole("button", { name: "Supply a prior" }));

    const readers = container.querySelectorAll(".tree-node.reader");
    expect(readers.length).toBe(1);
    expect(readers[0]!.className).toContain("tree-posterior");
    // Marked in words, not only in styling, so it survives a screenshot.
    expect(within(readers[0] as HTMLElement).getByText("your prior")).toBeInTheDocument();
    // And beneath the ratio rather than beside the tree: the posterior has to visibly depend on
    // the evidence it was computed from.
    const ratio = container.querySelector(".tree-likelihood_ratio")!;
    expect(ratio.contains(readers[0]!)).toBe(true);
  });

  it("swaps the caveats the moment a posterior is drawn", () => {
    const { container } = draw(loaded(ratioNoPrior));
    fireEvent.click(screen.getByRole("button", { name: "Supply a prior" }));
    const limitations = container.querySelector(".limitations")!.textContent ?? "";
    expect(limitations).not.toBe(ratioNoPrior.limitations);
    expect(limitations).toMatch(/not the library's/);
    expect(limitations).toMatch(/not saved/);
  });

  it("moves the posterior with the slider, using the pinned transform", () => {
    const ratio = findRatio(asTree(ratioNoPrior.root))!;
    const log10Lr = detailValue(ratio, "log10_lr") as number;
    const { container } = draw(loaded(ratioNoPrior));
    fireEvent.click(screen.getByRole("button", { name: "Supply a prior" }));
    fireEvent.change(screen.getByRole("slider"), { target: { value: "0" } });

    const expected = posteriorProbability(0.5, log10Lr);
    const drawn = container.querySelector(".tree-node.reader")!;
    expect(drawn.textContent).toContain(expected.toPrecision(4));
  });

  it("takes the posterior back out when the prior is cleared", () => {
    const { container } = draw(loaded(ratioNoPrior));
    fireEvent.click(screen.getByRole("button", { name: "Supply a prior" }));
    fireEvent.click(screen.getByRole("button", { name: "clear it" }));
    expect(container.querySelectorAll(".tree-node.reader").length).toBe(0);
    expect(container.querySelector(".limitations")!.textContent).toBe(ratioNoPrior.limitations);
  });

  it("offers no control when the document already names a prior", () => {
    const { container } = draw(loaded(withRatio));
    expect(screen.queryByRole("button", { name: "Supply a prior" })).toBeNull();
    expect(screen.queryByRole("slider")).toBeNull();
    // The posteriors on screen are the document's own, so the caveats are the document's too.
    expect(container.querySelectorAll(".tree-node.reader").length).toBe(0);
    expect(container.querySelector(".limitations")!.textContent).toBe(withRatio.limitations);
    // The control names the supplier. Scoped to the control, because the document's own posterior
    // step carries the same name as a detail row — and both saying it is the point.
    const control = container.querySelector(".prior")!;
    expect(within(control as HTMLElement).getByText("the fixture")).toBeInTheDocument();
  });

  it("says a withheld ratio has nothing for a prior to update", () => {
    draw(loaded(noRatio));
    expect(screen.getByText(/was not computed, so a prior has nothing to update/)).toBeInTheDocument();
    expect(screen.queryByRole("slider")).toBeNull();
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

/**
 * The prose pane, wired: a narrative is keyed by the claim it is about, and the pane shows the prose
 * for whichever claim the reader is looking at. Nothing else would make it visible.
 */
describe("the narrative", () => {
  it("renders beside the argument it is about", () => {
    const store = addNarrative(loaded(noRatio), narrative);
    draw(store);
    expect(screen.getByRole("heading", { level: 3, name: /Narrative/ })).toBeInTheDocument();
    expect(screen.getByText(/The claim names a transfer/)).toBeInTheDocument();
    expect(screen.getByText(/fixture, prompt v1/)).toBeInTheDocument();
  });

  it("says which steps of the derivation have no prose", () => {
    draw(addNarrative(loaded(noRatio), narrative));
    expect(screen.getByText(/1 step\(s\) of the derivation have no paragraph/)).toBeInTheDocument();
  });

  it("shows nothing at all when no narrative was loaded", () => {
    // The normal case: a narrative is a view of a derivation, not part of it.
    draw(loaded(noRatio));
    expect(screen.queryByRole("heading", { level: 3, name: /Narrative/ })).toBeNull();
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
