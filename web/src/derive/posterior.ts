/**
 * The one piece of arithmetic the browser does, and why it is allowed to.
 *
 * The library ships **no default prior** and reports **no posterior**. A prior is an assumption
 * only a person can supply, so the app makes it a view parameter: a slider whose default state is
 * *absent*, so no posterior exists anywhere until somebody moves it.
 *
 * That framing is the whole reason this file is allowed to exist. The alternative — round-tripping
 * each drag to a local server — would be laggy, impossible in the static mode the app is built to
 * run in, and would put the prior in a document, where it would read as the library's when it is
 * not. Doing it here means the prior is visibly the reader's: it never leaves the browser, it is
 * never written down, and the replacement limitations text (below) says so.
 *
 * The cost is that the arithmetic now exists twice. It is pinned by
 * `tests/ui/fixtures/posterior_cases.json`: 110 rows of `(prior, log10_lr, expected)` produced by
 * :meth:`LikelihoodRatio.posterior_probability` on ratios built by the real engine, asserted here
 * at 1e-12, plus the priors that implementation refuses and the unbounded case it cannot price.
 *
 * **The reference implementation is named so a reader can check this against it:**
 * ``LikelihoodRatio.posterior_probability`` in `src/chainlens/verify/likelihood.py` — ``odds =
 * exp(logit(prior) + log10_lr·ln 10)``, then ``odds / (1 + odds)``.
 */

/** `ln 10`, for converting a base-10 logarithm into natural log-odds. */
const LN_10 = Math.LN10;

/**
 * The posterior probability, given a prior the reader supplied.
 *
 * Throws rather than returning a fallback, for the same reason the library does: a prior of
 * exactly 0 or 1 cannot be moved by any amount of evidence, so it is a mistake rather than a
 * belief, and silently substituting something else would hide that. A ratio with no finite
 * logarithm cannot be updated at all — an infinite ratio times any prior is still infinite — so
 * that is refused too, with its own message because the cause is different and the reader can act
 * on only one of them.
 */
export function posteriorProbability(prior: number, log10Lr: number): number {
  if (!Number.isFinite(prior) || !(prior > 0) || !(prior < 1)) {
    throw new Error(
      `a prior must lie strictly between 0 and 1 to be updatable, got ${String(prior)}`,
    );
  }
  if (!Number.isFinite(log10Lr)) {
    throw new Error(
      `cannot update a ratio with no finite logarithm, got ${String(log10Lr)}: the ratio is ` +
        "unbounded, so no prior can move it",
    );
  }
  const priorLogOdds = Math.log(prior / (1 - prior));
  const posteriorLogOdds = priorLogOdds + log10Lr * LN_10;
  const odds = Math.exp(posteriorLogOdds);
  return odds / (1 + odds);
}

/** Whether a value can be used as a prior, so a control can refuse before arithmetic throws. */
export function isUpdatablePrior(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 && value < 1;
}

/**
 * The range the control spans, in **log-odds** rather than probability.
 *
 * A linear probability slider is useless across the range a prior actually occupies: everything
 * below 1% is in the first pixel, and the difference between 0.999 and 0.9999 is invisible. The
 * library insists on log-odds from a caller for the same reason, and this is the same decision
 * made visual.
 */
export const PRIOR_LOG_ODDS_RANGE = { min: -6, max: 6, step: 0.05 } as const;

/** The probability a log-odds expresses. */
export function probabilityFromLogOdds(logOdds: number): number {
  const odds = Math.pow(10, logOdds);
  return odds / (1 + odds);
}

/** How a probability is written for a reader: "1 in 1,000" is legible where "0.001" is not. */
export function describeProbability(probability: number): string {
  if (probability >= 0.01) return probability.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  const denominator = Math.round(1 / probability);
  return `${probability.toExponential(2)} — about 1 in ${denominator.toLocaleString("en")}`;
}

/**
 * What replaces the document's limitations text when the reader supplies a prior here.
 *
 * The document carries the library's standing text, which says a likelihood ratio "is not the
 * probability that the claim is true". That sentence is right about the ratio and wrong about the
 * screen once a posterior is drawn on it: a posterior *is* a probability of the claim, under a
 * prior the sentence does not mention. So the text is swapped rather than merely added to — a
 * number sitting beside a sentence denying it leaves the reader to decide which half to believe.
 *
 * This is deliberately **not** a copy of the library's `PRIOR_LIMITATIONS`. That text is written
 * for a finding where a caller supplied a prior through the API, and it names them; this one is
 * about a slider in a browser, and the honest difference is worth keeping rather than smoothing
 * over — it is the difference between a finding that records its terms and a reader looking at
 * what-ifs.
 */
export const READER_PRIOR_LIMITATIONS =
  "A posterior is shown, and it is not the library's. The likelihood ratio is the weight of the " +
  "evidence; the prior is the assumption you set in this browser, and the posterior is those two " +
  "combined. Your prior was not sent anywhere, is not in the document, and is not saved — the " +
  "library reports no posterior, so the figure beside this text is a composition made here rather " +
  "than a finding anything computed. Move the prior and the posterior moves with it; neither is " +
  "robust to how the claim was selected.";
