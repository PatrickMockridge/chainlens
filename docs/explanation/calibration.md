# Is a likelihood ratio any good?

A likelihood ratio is a claim about how much more likely the evidence is under one proposition
than another. Nothing about computing one asks whether those claims are *true* — whether a ratio of
1,000 is worth more than one of 100, or whether either means what it says. `chainlens.verify.calibration`
exists to answer that, with the cost function forensic science uses for the purpose.

## The metric

```
Cllr = 1/(2·N_same) · Σ_same log₂(1 + 1/LR) + 1/(2·N_diff) · Σ_diff log₂(1 + LR)
```

The average cost, in bits, of decisions made from the ratios. It is `1` for a system that reports
"no information" — every ratio exactly 1 — whatever the class balance, and lower is better. Splitting
it is where the diagnosis lives:

```
calibration_loss = Cllr - Cllr_min
```

`Cllr_min` is what the ratios could cost after the best possible *monotone* re-mapping of the
scores, computed with pool adjacent violators. A large gap means the ratios **rank** cases well and
sit on the wrong scale: a recalibration would fix it, and it says nothing about the evidence. A
small gap with a large `Cllr` means the ratios rank badly, which no recalibration can fix, because
it is a statement about the evidence itself.

## Two things to know before reading a number

**The floor of `Cllr` here is 0.5, not 0.** This library will not report a ratio below 1: a matched
transfer cannot count against the claim it matches. The best a different-source case can therefore
score is `LR = 1`, which costs a full bit weighted by `1/(2·N_diff)` — half a bit overall. A `Cllr`
near 0.5 is a *perfect* score for this library, not a mediocre one. `Cllr_min` has no such floor,
because a recalibration is not bound by that rule and may map a score band below 1.

**A corpus needs both classes.** With only same-source or only different-source cases, every set of
ratios costs the same, so the number would look like a result and mean nothing. That is refused
rather than reported.

## The hard part is ground truth, and this repository does not have it

Calibration compares ratios against **truth**, and a verdict is not truth. `SUPPORTED` means the
chain data is consistent with the claim; a supported claim can be false, and a contradicted one can
rest on a provider that did not index the right address. So a corpus of claim records with expected
verdicts cannot calibrate anything — it would measure the library against itself.

What calibration needs is pairs whose truth is known *independently*: cases where somebody has
established whether the asserted payment really is the one the chain recorded. The test suite builds
such a corpus synthetically, where the truth is the generator's parameter, and that measures the
arithmetic and the plumbing. It says nothing about real-world accuracy, and the module says so in
its own docstring rather than leaving it to be inferred.

Until real labelled data exists, the honest position is the one the library takes elsewhere: **a
ratio from this estimator is arguable, not validated.**

## What a report keeps apart

Coverage is as important as the cost, so the report separates three ways a case can end:

| | meaning |
|---|---|
| **priced** | a ratio was reported, and it is one of the trials the cost is over |
| **refused** | a ratio was expected and not reported — the estimator's reason is counted, so a pattern in *why* is visible |
| **not applicable** | the verdict cannot carry a ratio at all — a contradicted claim cannot, by design |

Coverage is over priceable cases only. Counting a contradiction as a missing ratio would blame the
estimator for arithmetic.

```python
from chainlens.verify.calibration import GroundTruth, case_from_finding, report_from_cases

cases = [
    case_from_finding("0001", GroundTruth.SAME_SOURCE, finding_0001),
    case_from_finding("0002", GroundTruth.DIFFERENT_SOURCE, finding_0002),
]
print(report_from_cases(cases).format())
```

An unbounded ratio makes the cost infinite when it lands on a different-source case, and costs
nothing when it lands on a same-source one. That is the metric agreeing with the library's own rule
about infinities: claiming certainty about the wrong thing is the worst answer available.
