# The sensitivity of a ratio

**Status: Specified.** `Sensitivity.lean` arrives in T5, and T5 is the tranche that can be dropped.
It is the only layer that needs Mathlib.

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

| Claim | Statement | Status |
|---|---|---|
| monotonicity | `LR` is non-decreasing in `k` and non-decreasing in `p` | Specified — T5 |
| the derivative | `∂LR/∂k` and `∂LR/∂p` in closed form, and their signs | Specified — T5 |
| the interval is an interval | the reported range contains the point estimate and its ends are ordered | Specified — T5 |

The third is the one a reader would not think to doubt. It is stated because the library carries an
interval on the wire and a `lower > upper` row is exactly the kind of defect that a type catches
and a reader does not.

## Why it needs Mathlib, and why that is the price

`differentiable`, `HasDerivAt` and the real analysis the derivative claim is stated in are all
Mathlib. Every other layer here is stated against Lean core alone, which is what keeps a
contributor's first `lake build` from being an hours-long dependency build. **So this layer is
sequenced next to last.** If `lake exe cache get` turns out to be impractical on a contributor's
machine, this layer stays Specified and the other eight are unaffected — the drop is designed in
rather than discovered.

## What is *not* a claim here

**No claim that the ratio is robust to how the claim was selected.** It is not, and the library
says so instead of proving something adjacent. A likelihood ratio is conditional on a proposition,
and a proposition chosen after the finding was seen was chosen with the evidence in view. That is a
statement about a *selection*, and the place it is dealt with is
[the keycard](./capability.md) — where a selection is recorded and disclosed — and not here.

## What it is about in the tree

| The claim's subject | The tree |
|---|---|
| the ratio, and the coincidence probability it divides | `src/chainlens/verify/likelihood.py::likelihood_ratio` and `::coincidence_probability` |
| the interval | `src/chainlens/verify/likelihood.py::wilson_interval` |
| the guard that the count is complete | `src/chainlens/verify/checks/base.py::CheckContext.scan_limit` |

The closed forms the library reports are already written down beside their implementations — the
`OperationKind` table in `src/chainlens/verify/likelihood.py` maps each operation to the expression
a reader recomputes by hand — so the page and the code already name the same three formulas. What
T5 adds is that they have the signs they are claimed to have.
