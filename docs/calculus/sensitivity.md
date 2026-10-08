# The sensitivity of a ratio

**Status: Proved.** `lean/Chainlens/Sensitivity.lean` builds, and all thirteen theorems are in
`Axioms.lean` and rest on nothing outside the three axioms the gate permits. It is the one module
here that depends on Mathlib, and that was a cost measured rather than assumed — see below.

## What it fixes

How a likelihood ratio moves with its own two terms, and that the interval the library reports is
an interval.

## The claims

A coincidence has `k` opportunities and a per-opportunity probability `p`, and the ratio is

```
LR = 1 / (1 - (1 - p)^k)
```

`k` is a **count of transactions the walk actually saw**, not an estimate, and `p` is read from a
corpus. Both are inputs, and a reader is entitled to know which of them the answer is fragile to.

| Claim | Theorem | Status |
|---|---|---|
| the coincidence probability is one | `coincidence_is_probability`, `coincidence_nonneg`, `coincidence_le_one` | Proved |
| its step is exactly `p·(1-p)^k` | `coincidence_step` | Proved |
| it rises with both arguments | `coincidence_mono_p`, `coincidence_mono_k`, `coincidence_pos` | Proved |
| the ratio falls with both | `ratio_antitone_p`, `ratio_antitone_k` | Proved |
| the ratio is never below one | `ratio_ge_one` | Proved |
| the interval is an interval | `wilsonSpread_nonneg`, `wilson_ordered` | Proved |
| it contains the estimate | `wilson_contains_estimate` | Proved |

**The two functions move in opposite directions and that is the whole content of the layer.** A
likelier coincidence and more opportunities each make a match **less** surprising, so the
coincidence probability rises and the ratio falls toward 1. Measured:

| | values |
|---|---|
| coincidence `(k, p=0.5)` for `k = 1, 2, 5, 10` | 0.5, 0.75, 0.969, 0.999 |
| ratio `(k, p=0.5)` for `k = 1, 2, 5, 10` | 2.0, 1.333, 1.032, 1.001 |
| ratio `(k=5, p)` for `p = 0.01, 0.05, 0.1, 0.5` | 20.4, 4.42, 2.44, 1.03 |

**This table was wrong twice, in two different ways, and the second is the more instructive.**
It first said the ratio is *non-decreasing* in `k` and in `p`, which has both signs backwards —
found by checking the claim against the code rather than against the intuition that "more evidence
is better". Then the corrected direction was carried into the Lean brief, where the *coincidence
probability* was named antitone in `k`: also wrong, and wrong in the opposite direction from the
first error, because the two functions' directions are opposites and it is easy to fix the sign on
one and move the other with it. Both were caught by writing the claim down as a statement a
machine has to accept.

**The page also claimed a derivative, and there is no derivative to prove.** `k` in this library is
a count of transactions the walk actually saw — an integer, never a real — so the continuous
extension a `∂LR/∂k` would need does not exist in the code, and a theorem about it would be a
theorem about a function nobody calls. What *is* exact is the increment: the coincidence
probability's step is `p·(1-p)^k`, and the ratio's step is its negation scaled — a difference, not
a derivative, and the honest version of "how the ratio moves with `k`".

**And one boundary the model does not share with the code.** `likelihood_ratio` returns `math.inf`
where the coincidence probability is zero — at `p = 0`, and at `k = 0`. Lean's `(0:ℝ)⁻¹` is `0`,
so a total Lean function would say "no evidence at all" exactly where the library says "infinite
evidence". The theorems therefore require `0 < p` and `0 < k` rather than asserting through the
point, and the boundary is a stated difference between the model and the function rather than a
hypothesis nobody explains.

The interval claim is the one a reader would not think to doubt. It is stated because the library
carries an interval on the wire and a `lower > upper` row is exactly the kind of defect that a type
catches and a reader does not — and because the interval's *containment* of the point estimate is a
real theorem rather than an artefact of how it is computed.

## Why it needs Mathlib, and what that actually costs

**This is the one layer stated over `ℝ`.** The coincidence probability is `1 - (1 - p)^k` for a
real `p`, the ratio inverts it, and the Wilson interval's half-width is a `Real.sqrt` — so this
module needs Mathlib's real arithmetic, where the other eight are stated against Lean core alone.
That asymmetry is deliberate: seven of the nine layers are about integers and sets, and one is
about a probability.

**That paragraph was a blocker asserted rather than measured, and the measurement is two minutes.**
Mathlib is a dependency now; `lake exe cache get` fetches 7,335 prebuilt oleans in about two
minutes, one module reads them, and the other eight still build against Lean core alone. The
"hours" figure is what a from-source build costs, and it is not what a contributor pays. The
layer was sequenced last on the strength of that wrong number, and it is the case in this
repository where "we will do it later because it looks expensive" turned out to be the expensive
choice: the wrong signs sat on this page while the work was deferred.

## What is *not* a claim here

**No claim that the ratio is robust to how the claim was selected.** It is not, and the library
says so instead of proving something adjacent. A likelihood ratio is conditional on a proposition,
and a proposition chosen after the finding was seen was chosen with the evidence in view. That is a
statement about a *selection*, and the place it is dealt with is
[the keycard](./capability.md) — where a selection is recorded and disclosed — and not here.

## What it is about in the tree

| Lean | The tree |
|---|---|
| `Chainlens.Sensitivity.coincidence` | `src/chainlens/verify/likelihood.py::coincidence_probability` |
| `Chainlens.Sensitivity.ratio` | `src/chainlens/verify/likelihood.py::likelihood_ratio` |
| `wilsonCentre` / `wilsonSpread` / `wilsonLower` / `wilsonUpper` | `src/chainlens/verify/likelihood.py::wilson_interval` |
| the guard that the count is complete | `src/chainlens/verify/checks/base.py::CheckContext.scan_limit` |

The closed forms the library reports are already written down beside their implementations — the
`OperationKind` table in `src/chainlens/verify/likelihood.py` maps each operation to the expression
a reader recomputes by hand — so the page and the code already name the same three formulas. What
this layer adds is that they have the signs they are claimed to have.

**Two things the Lean model does not carry, and both are stated rather than absorbed.** The
`wilson_interval` in the tree clips its output to `[0, 1]` and rounds away a floating-point
artefact at the endpoints; neither is modelled, because both are about the representation of a
float and not about the interval. And the estimator's `p` is a `float` read from data, where Lean's
is a real — the same `float`-versus-`ℝ` gap that [layer 3](./exactness.md) found a live bug in, and
here it is bounded rather than load-bearing because nothing is summed.
