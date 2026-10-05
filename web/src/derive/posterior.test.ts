/**
 * The prior transform, checked against the library's own answers.
 *
 * The goldens are not a re-derivation of the formula with different rounding — every `expected`
 * in the fixture was computed by calling `LikelihoodRatio.posterior_probability` on a ratio
 * assembled by `evaluate_likelihood`, and written out by `tests/ui/posterior_cases.py`. So if the
 * library's arithmetic changed, this fails; if this copy drifts, this fails; and the two cannot
 * agree with each other while both being wrong about the mathematics, because the comparison is
 * against the implementation that produced the numbers rather than against a table somebody
 * typed.
 *
 * 1e-12 rather than an exact comparison: the two implementations call the same libm functions in
 * principle, but Python's `math.log` and JavaScript's `Math.log` are not required to be
 * bit-identical, and a test that demanded that would be asserting a property nobody promises.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { READER_PRIOR_LIMITATIONS, isUpdatablePrior, posteriorProbability } from "./posterior";

interface Case {
  k: number;
  successes: number;
  lr: number;
  log10_lr: number;
  prior: number;
  expected: number;
}

const here = dirname(fileURLToPath(import.meta.url));
const fixture = JSON.parse(
  readFileSync(join(here, "..", "..", "..", "tests", "ui", "fixtures", "posterior_cases.json"), "utf8"),
) as {
  reference: string;
  cases: Case[];
  rejected_priors: { prior: number; reason: string }[];
  unbounded: { log10_lr: null; lr_is_infinite: boolean };
};

describe("the prior transform", () => {
  it("reproduces every golden the library produced", () => {
    expect(fixture.cases.length).toBeGreaterThan(100);
    for (const row of fixture.cases) {
      const got = posteriorProbability(row.prior, row.log10_lr);
      expect(Math.abs(got - row.expected)).toBeLessThan(1e-12);
    }
  });

  it("names the implementation it is a copy of", () => {
    // The fixture records where its expected values came from, so the copy cannot quietly become
    // the only description of the arithmetic.
    expect(fixture.reference).toBe(
      "chainlens.verify.likelihood.LikelihoodRatio.posterior_probability",
    );
  });

  it("leaves the posterior at the prior when the evidence is worth nothing", () => {
    // `log10_lr = 0` is a ratio of exactly 1: the evidence does not move the belief. It is the
    // case an implementation that used odds where it meant log-odds would get most visibly wrong.
    for (const prior of [0.001, 0.5, 0.9]) {
      expect(posteriorProbability(prior, 0)).toBeCloseTo(prior, 12);
    }
  });

  it("moves in the direction the ratio points", () => {
    expect(posteriorProbability(0.5, 2)).toBeGreaterThan(0.5);
    expect(posteriorProbability(0.5, -2)).toBeLessThan(0.5);
  });

  it("refuses every prior the library refuses", () => {
    const ratio = 1905.16;
    for (const rejected of fixture.rejected_priors) {
      expect(() => posteriorProbability(rejected.prior, ratio)).toThrow(/between 0 and 1/);
    }
  });

  it("refuses the priors JSON cannot carry, which the fixture therefore cannot list", () => {
    // NaN and the infinities are rejected by the library too, but a JSON file cannot hold them,
    // so they are asserted here rather than shipped as `null` — which would be a different value
    // from the one the library rejects.
    for (const value of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]) {
      expect(() => posteriorProbability(value, 3)).toThrow(/between 0 and 1/);
    }
  });

  it("refuses a ratio with no finite logarithm, with its own reason", () => {
    // An infinite ratio is a different failure from an unusable prior: the reader can fix one by
    // moving a slider and cannot fix the other at all, so the messages do not read alike.
    expect(fixture.unbounded.log10_lr).toBeNull();
    expect(fixture.unbounded.lr_is_infinite).toBe(true);
    for (const prior of [0.001, 0.5]) {
      expect(() => posteriorProbability(prior, Number.POSITIVE_INFINITY)).toThrow(/unbounded/);
      expect(() => posteriorProbability(prior, Number.NaN)).toThrow(/unbounded/);
    }
  });

  it("answers whether a prior is usable without throwing", () => {
    expect(isUpdatablePrior(0.001)).toBe(true);
    expect(isUpdatablePrior(0)).toBe(false);
    expect(isUpdatablePrior(1)).toBe(false);
    expect(isUpdatablePrior(Number.NaN)).toBe(false);
    expect(isUpdatablePrior("0.5")).toBe(false);
    expect(isUpdatablePrior(null)).toBe(false);
  });
});

describe("the replacement limitations text", () => {
  it("says whose prior it is and that nothing was sent anywhere", () => {
    // The three things the swapped text has to carry, because the text it replaces asserted the
    // opposite of the first and is silent on the other two.
    expect(READER_PRIOR_LIMITATIONS).toMatch(/not the library's/);
    expect(READER_PRIOR_LIMITATIONS).toMatch(/not sent anywhere/);
    expect(READER_PRIOR_LIMITATIONS).toMatch(/not saved/);
  });
});
