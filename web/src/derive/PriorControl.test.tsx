/**
 * The prior control, and the four states it has to tell apart.
 *
 * The control's hardest requirement is not arithmetic — that is pinned in `posterior.test.ts` —
 * but *restraint*: it must not offer a prior where a prior would be meaningless (no ratio), move
 * nothing (an unbounded ratio), or overwrite an attribution the library deliberately recorded (a
 * document that already names who supplied one). Each of those is a way of putting a number on the
 * screen that nothing supports, so each is asserted separately.
 *
 * The formulas are asserted against `posteriorProbability`, which is itself checked against the
 * library's answers, rather than against hand-typed expected values — a second table of numbers
 * typed into a test would be a third description of the arithmetic.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";

import type { DerivationDocument, DerivationNode } from "../schema/documents";
import { asTree } from "../schema/documents";
import { posteriorProbability, probabilityFromLogOdds } from "./posterior";
import { PriorControl, planPosterior } from "./PriorControl";
import { detailValue, findRatio, walkTree } from "./tree";

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(
  readFileSync(join(here, "..", "..", "..", "tests", "ledger", "fixtures", "graph-document.json"), "utf8"),
) as { derivations: Record<string, DerivationDocument> };

const noRatio = fixtures.derivations["no_ratio"]!;
const ratioNoPrior = fixtures.derivations["ratio_without_prior"]!;
const withPrior = fixtures.derivations["with_ratio"]!;

/** The same document with its ratio declared unbounded, the way the wire writes one. */
function unbounded(document: DerivationDocument): DerivationDocument {
  const root = asTree(document.root);
  const ratio = findRatio(root)!;
  return {
    ...document,
    root: {
      ...root,
      children: (root.children ?? []).map((child) =>
        child.id === ratio.id
          ? {
              ...child,
              detail: (child.detail ?? []).map((entry) =>
                entry.key === "log10_lr"
                  ? { ...entry, value: null }
                  : entry.key === "lr_at_least"
                    ? { ...entry, value: true }
                    : entry,
              ),
            }
          : child,
      ),
    },
  } as DerivationDocument;
}

describe("planning what a prior implies", () => {
  it("offers nothing in the no-ratio shape, because there is nothing to update", () => {
    const plan = planPosterior(noRatio, -3);
    expect(plan.ratioNode).toBeNull();
    expect(plan.offerable).toBe(false);
    expect(plan.extraChildren).toBeUndefined();
    expect(plan.limitations).toBeUndefined();
  });

  it("offers the control for a ratio with no prior", () => {
    const plan = planPosterior(ratioNoPrior, null);
    expect(plan.ratioNode).not.toBeNull();
    expect(plan.offerable).toBe(true);
    // Offered, but nothing drawn until a person moves it.
    expect(plan.prior).toBeNull();
    expect(plan.posterior).toBeNull();
  });

  it("attaches the posterior beneath the ratio, where the arithmetic puts it", () => {
    const plan = planPosterior(ratioNoPrior, -3);
    const ratio = plan.ratioNode!;
    const attached = plan.extraChildren!.get(ratio.id)!;
    expect(attached).toHaveLength(1);
    expect(attached[0]!.kind).toBe("posterior");
    // Beneath the ratio and nowhere else: a posterior beside the tree would not visibly depend on
    // the evidence that produced it.
    expect(plan.extraChildren!.size).toBe(1);
    expect(plan.readerSteps!.has(attached[0]!.id)).toBe(true);
  });

  it("computes the posterior the pinned transform computes", () => {
    const plan = planPosterior(ratioNoPrior, -3);
    const log10Lr = detailValue(plan.ratioNode!, "log10_lr") as number;
    const prior = probabilityFromLogOdds(-3);
    expect(plan.prior).toBeCloseTo(prior, 15);
    expect(plan.posterior).toBeCloseTo(posteriorProbability(prior, log10Lr), 15);
  });

  it("swaps the limitations text, because the document's own reads as denying the posterior", () => {
    const plan = planPosterior(ratioNoPrior, -3);
    // The sentence that makes the swap necessary. It is right about the ratio and wrong about a
    // screen that also carries a posterior: a posterior *is* a probability of the claim, under a
    // prior the sentence does not mention.
    expect(ratioNoPrior.limitations).toMatch(/not the probability that the claim is true/);
    expect(plan.limitations).toBeDefined();
    expect(plan.limitations).not.toBe(ratioNoPrior.limitations);
    expect(plan.limitations).toMatch(/not the library's/);
  });

  it("refuses to offer a prior for an unbounded ratio, and says so rather than failing later", () => {
    const plan = planPosterior(unbounded(ratioNoPrior), -3);
    expect(plan.ratioNode).not.toBeNull();
    expect(plan.unbounded).toBe(true);
    expect(plan.offerable).toBe(false);
    expect(plan.posterior).toBeNull();
    // No posterior, so the document's limitations text stands rather than being swapped.
    expect(plan.limitations).toBeUndefined();
  });

  it("does not offer to replace a prior the document already names", () => {
    const plan = planPosterior(withPrior, -3);
    expect(plan.alreadySuppliedBy).toBe("the fixture");
    expect(plan.offerable).toBe(false);
    expect(plan.posterior).toBeNull();
    // The document's own posterior stays; nothing is drawn beside it.
    expect(plan.extraChildren).toBeUndefined();
  });

  it("keeps the reader's prior out of the document", () => {
    // The document is a fixture object; planning must not have written to it. A prior that reached
    // a document would read as the library's, which is the one thing this design refuses.
    const before = JSON.stringify(ratioNoPrior);
    planPosterior(ratioNoPrior, -3);
    expect(JSON.stringify(ratioNoPrior)).toBe(before);
    expect(walkTree(asTree(ratioNoPrior.root)).some((node) => node.kind === "posterior")).toBe(false);
  });
});

describe("the control", () => {
  function draw(props: Partial<React.ComponentProps<typeof PriorControl>> = {}) {
    const plan = props.plan ?? planPosterior(ratioNoPrior, props.logOdds ?? null);
    return render(
      <PriorControl
        plan={plan}
        logOdds={props.logOdds ?? null}
        onChange={props.onChange ?? (() => undefined)}
      />,
    );
  }

  it("starts with no prior and explains why", () => {
    draw();
    expect(screen.getByText(/ships no prior and reports no posterior/)).toBeInTheDocument();
    expect(screen.queryByRole("slider")).toBeNull();
    expect(screen.queryByText(/posterior/)).not.toBeNull();
  });

  it("hands a supplied prior to the view rather than keeping it", () => {
    const onChange = vi.fn();
    draw({ onChange });
    fireEvent.click(screen.getByRole("button", { name: "Supply a prior" }));
    expect(onChange).toHaveBeenCalledTimes(1);
    // A number, so the view can compute with it — and not a probability, because the slider it
    // drives spans log-odds.
    expect(typeof onChange.mock.calls[0]![0]).toBe("number");
  });

  it("shows the prior as a probability a reader can read, and the posterior it implies", () => {
    const logOdds = -3;
    draw({ logOdds, plan: planPosterior(ratioNoPrior, logOdds) });
    expect(screen.getByRole("slider")).toHaveValue(String(logOdds));
    const posterior = posteriorProbability(probabilityFromLogOdds(logOdds), detailValue(
      findRatio(asTree(ratioNoPrior.root))!,
      "log10_lr",
    ) as number);
    expect(screen.getByText(posterior.toPrecision(4))).toBeInTheDocument();
    expect(screen.getByText(/1 in 1,001/)).toBeInTheDocument();
  });

  it("reports a move of the slider", () => {
    const onChange = vi.fn();
    draw({ logOdds: -3, onChange });
    fireEvent.change(screen.getByRole("slider"), { target: { value: "-1.5" } });
    expect(onChange).toHaveBeenCalledWith(-1.5);
  });

  it("can be cleared back to no prior at all", () => {
    const onChange = vi.fn();
    draw({ logOdds: -3, onChange });
    fireEvent.click(screen.getByRole("button", { name: "clear it" }));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("says the ratio is unbounded instead of offering a slider that would throw", () => {
    const document = unbounded(ratioNoPrior);
    draw({ plan: planPosterior(document, null) });
    expect(screen.queryByRole("slider")).toBeNull();
    expect(screen.getByText(/unbounded/)).toBeInTheDocument();
  });

  it("names whoever supplied the prior a document already carries", () => {
    draw({ plan: planPosterior(withPrior, null) });
    expect(screen.getByText("the fixture")).toBeInTheDocument();
    expect(screen.queryByRole("slider")).toBeNull();
  });

  it("says a derivation with no ratio has nothing to update", () => {
    draw({ plan: planPosterior(noRatio, null) });
    expect(screen.getByText(/reports no likelihood ratio/)).toBeInTheDocument();
  });
});

/** A guard on the fixture set: the three shapes these tests need must all still be there. */
describe("the derivation fixtures the control is tested against", () => {
  it("covers no ratio, a ratio with no prior, and a ratio with one", () => {
    expect(findRatio(asTree(noRatio.root))).toBeNull();
    expect(findRatio(asTree(ratioNoPrior.root))).not.toBeNull();
    expect(ratioNoPrior.prior_supplied_by).toBeNull();
    expect(withPrior.prior_supplied_by).toBe("the fixture");
    const node: DerivationNode = findRatio(asTree(withPrior.root))!;
    expect(detailValue(node, "log10_lr")).toBeTypeOf("number");
  });
});
