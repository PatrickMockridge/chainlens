/**
 * The prior control, and the plan it produces for the tree.
 *
 * **A prior is an assumption only a person can supply, so this control's default state is that
 * there is none.** No posterior is drawn, the document's own limitations text stands, and the
 * control says what the library does and does not do. Nothing is drawn from a manufactured
 * default, because a default prior is exactly the unexamined assumption the library refuses to
 * make — and a slider resting at 0.001 would be read as the app's belief rather than a starting
 * point.
 *
 * `planPosterior` holds every branch of that reasoning as one pure function, so the view renders
 * what it decides rather than deciding it. Four states, and each one exists:
 *
 * * **no ratio** — the ordinary case today. There is nothing a prior could update, so no control
 *   is offered and the tree is left alone.
 * * **an unbounded ratio** — a zero coincidence probability priced to an infinite ratio, which the
 *   wire writes as an absent logarithm plus `lr_at_least`. No prior can move an infinity, so the
 *   control says *that* rather than failing when somebody moves it.
 * * **the document already names a prior** — a finding computed with one carries its own posterior
 *   and names whoever supplied it. Replacing that with a slider would hide an attribution the
 *   library deliberately records, so the control is not offered and says whose prior is shown.
 * * **a ratio with no prior** — the case this exists for.
 */
import type { DerivationDocument, DerivationNode } from "../schema/documents";
import { asTree } from "../schema/documents";
import {
  PRIOR_LOG_ODDS_RANGE,
  describeProbability,
  posteriorProbability,
  probabilityFromLogOdds,
  READER_PRIOR_LIMITATIONS,
} from "./posterior";
import { detailNumber, findRatio } from "./tree";

export interface PosteriorPlan {
  /** The step a posterior would hang beneath, or `null` in the no-ratio shape. */
  readonly ratioNode: DerivationNode | null;
  /** The ratio's base-10 logarithm, or `null` when it is unbounded or withheld. */
  readonly log10Lr: number | null;
  /**
   * Whether the document shows the calculation and no result — the ratio was withheld, and the
   * artifact carries the formula with the input that stopped it.
   */
  readonly withheld: boolean;
  /** Whether the ratio is infinite, which no prior can move. */
  readonly unbounded: boolean;
  /** Whoever the document says supplied the prior it already holds, if it holds one. */
  readonly alreadySuppliedBy: string | null;
  /** Whether the control should be offered at all. */
  readonly offerable: boolean;
  /** The prior the reader set, as a probability, when they set one. */
  readonly prior: number | null;
  /** The resulting posterior, when one can be computed. */
  readonly posterior: number | null;
  /** The step to attach, under the ratio, when a posterior is drawn. */
  readonly extraChildren?: ReadonlyMap<string, DerivationNode[]>;
  /** Its identifier, so the renderer can mark it as the reader's. */
  readonly readerSteps?: ReadonlySet<string>;
  /** What replaces the document's limitations text, when a posterior is drawn. */
  readonly limitations?: string;
}

/**
 * Decide what a prior implies for one derivation.
 *
 * Pure, and total: an unusable declaration yields no posterior rather than an exception, because a
 * renderer that throws loses the whole page over one bad slider position.
 */
export function planPosterior(
  document: DerivationDocument,
  logOdds: number | null,
): PosteriorPlan {
  const ratioNode = findRatio(asTree(document.root));
  const alreadySuppliedBy = document.prior_supplied_by ?? null;
  const log10Lr = ratioNode === null ? null : detailNumber(ratioNode, "log10_lr");
  // A withheld ratio is not an unbounded one. Both carry no logarithm, and they mean opposite
  // things: a withheld ratio was never computed, so there is nothing for a prior to update,
  // while an unbounded one was computed and came out infinite, which no prior can move. Since
  // the redesign a no-ratio derivation *has* a ratio node — carrying the formula and the input
  // that stopped it — so "is there a ratio node" no longer answers "is there a ratio", and the
  // operation's own result is what does.
  const withheld = ratioNode?.operation != null && ratioNode.operation.result === null;
  const unbounded = !withheld && ratioNode !== null && log10Lr === null;
  const offerable =
    ratioNode !== null && !withheld && !unbounded && alreadySuppliedBy === null;

  const prior = offerable && logOdds !== null ? probabilityFromLogOdds(logOdds) : null;
  let posterior: number | null = null;
  if (ratioNode !== null && prior !== null && log10Lr !== null) {
    posterior = posteriorProbability(prior, log10Lr);
  }

  const base = {
    ratioNode,
    log10Lr,
    withheld,
    unbounded,
    alreadySuppliedBy,
    offerable,
    prior,
    posterior,
  };

  if (ratioNode === null || prior === null || posterior === null || log10Lr === null) {
    return base;
  }

  const step = readerPosteriorStep(ratioNode, prior, posterior, log10Lr);
  return {
    ...base,
    extraChildren: new Map([[ratioNode.id, [step]]]),
    readerSteps: new Set([step.id]),
    limitations: READER_PRIOR_LIMITATIONS,
  };
}

/**
 * The posterior step, built here rather than shipped in the document.
 *
 * It names its prior and who chose it, and it carries no `graph_refs`: a posterior rests on an
 * assumption and the ratio, and neither is a ledger key, so highlighting anything in the graph for
 * it would be claiming a link the arithmetic does not make.
 */
function readerPosteriorStep(
  ratioNode: DerivationNode,
  prior: number,
  posterior: number,
  log10Lr: number,
): DerivationNode {
  return {
    id: `${ratioNode.id}/posterior:reader`,
    kind: "posterior",
    label: `posterior ${posterior.toPrecision(4)}`,
    summary:
      `from a prior of ${describeProbability(prior)} that you set here — not the library's, ` +
      "and not recorded anywhere",
    detail: [
      { key: "prior_probability", kind: "float", value: prior },
      { key: "posterior_probability", kind: "float", value: posterior },
      { key: "log10_lr", kind: "float", value: log10Lr },
      { key: "supplied_by", kind: "string", value: "you, in this browser" },
    ],
    value: posterior,
    band: null,
    graph_refs: [],
  };
}

export interface PriorControlProps {
  readonly plan: PosteriorPlan;
  readonly logOdds: number | null;
  readonly onChange: (logOdds: number | null) => void;
}

export function PriorControl({ plan, logOdds, onChange }: PriorControlProps) {
  if (plan.ratioNode === null) {
    return (
      <section className="prior">
        <h3>Prior</h3>
        <p className="hint">
          This finding has no likelihood ratio and no calculation that would have produced one —
          a contradicted claim, whose ratio is unavailable in principle rather than withheld. There
          is nothing for a prior to update, so none is offered.
        </p>
      </section>
    );
  }

  if (plan.withheld) {
    return (
      <section className="prior">
        <h3>Prior</h3>
        <p className="hint">
          The ratio was not computed, so a prior has nothing to update. The step above shows the
          formula that would have produced it and the input that stopped it, and says which kind
          of missing that input is. This is not the same as a ratio that came out unbounded: there
          the arithmetic ran and the answer was infinite.
        </p>
      </section>
    );
  }

  if (plan.unbounded) {
    return (
      <section className="prior">
        <h3>Prior</h3>
        <p className="hint">
          The ratio is unbounded: the coincidence probability came out at exactly zero, so the
          ratio is infinite and the wire records it as <code>at least</code> the largest finite
          figure rather than as a number. No prior moves an infinity, so none is offered.
        </p>
      </section>
    );
  }

  if (plan.alreadySuppliedBy !== null) {
    return (
      <section className="prior">
        <h3>Prior</h3>
        <p className="hint">
          This document already carries a posterior, from a prior supplied by{" "}
          <strong>{plan.alreadySuppliedBy}</strong>. The library records who supplied a prior, so
          this view shows theirs rather than offering to replace it — an attribution that a slider
          would quietly overwrite.
        </p>
      </section>
    );
  }

  return (
    <section className="prior">
      <h3>Prior</h3>
      {logOdds === null ? (
        <>
          <p className="hint">
            The library ships no prior and reports no posterior, because a base rate is an
            assumption only you can make. Supply one to see what it implies — it stays in this
            browser and is written nowhere.
          </p>
          <button type="button" onClick={() => onChange(-3)}>
            Supply a prior
          </button>
        </>
      ) : (
        <>
          <label className="prior-row">
            <span className="prior-label">your prior</span>
            <input
              type="range"
              aria-label="prior log odds"
              min={PRIOR_LOG_ODDS_RANGE.min}
              max={PRIOR_LOG_ODDS_RANGE.max}
              step={PRIOR_LOG_ODDS_RANGE.step}
              value={logOdds}
              onChange={(event) => onChange(Number(event.target.value))}
            />
          </label>
          <p className="prior-readout">
            p(claim) = <strong>{describeProbability(plan.prior ?? 0)}</strong>
            {plan.posterior !== null && (
              <>
                {" "}
                → p(claim | evidence) = <strong>{plan.posterior.toPrecision(4)}</strong>
              </>
            )}
          </p>
          <button type="button" className="link" onClick={() => onChange(null)}>
            clear it
          </button>
        </>
      )}
    </section>
  );
}
