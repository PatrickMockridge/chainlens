# `chainlens.verify.calibration`

The Cllr harness: whether the ratios the library reports are any good.

A likelihood ratio is a claim about how much more likely the evidence is under one proposition
than another. Nothing so far asks whether those claims are *true* — whether a ratio of 1,000 is
worth more than one of 100, or whether either means what it says. That is what a cost function is
for, and the standard one in forensic science is the **log-likelihood-ratio cost**:

    Cllr = 1/(2·N_same) · Σ_same log₂(1 + 1/LR) + 1/(2·N_diff) · Σ_diff log₂(1 + LR)

It is the average cost, in bits, of decisions made from the ratios, and it is 0 for a perfect
soft classifier and 1 for one that answers "no information" — every ratio exactly 1 — whatever the
class balance. Splitting it into the part a *recalibration* could recover and the part it could not
is the whole value::

    calibration_loss = Cllr - Cllr_min

``Cllr_min`` is the cost after the best possible monotone re-mapping of the scores, computed with
pool adjacent violators over the trials ordered by score. A large gap means the ratios *rank*
cases well but are not on the right scale — a fixable problem, and a different one from ratios that
rank badly.

**Ground truth is the hard part, and it is not something this repository has.** A verdict is not
ground truth: ``SUPPORTED`` means the chain data is consistent with the claim, and a supported
claim can be false. So a corpus of claim records with expected verdicts cannot calibrate anything
— what calibration needs is *pairs whose truth is known independently*, which for claims means
knowing whether the asserted payment is the one in the window. The test suite builds such a corpus
synthetically, where the truth is the generator's parameter; that measures the arithmetic and the
plumbing, and says nothing about real-world accuracy. A real number needs real labelled data, and
until it exists the honest position is that this library's ratios are arguable rather than
validated.

Two properties of the metric are worth knowing before reading a number:

* **the floor of ``Cllr`` is 0.5, not 0.** The library will not report a ratio below 1 — a matched
  transfer cannot count against the claim it matches — so the best a different-source case can ever
  score is ``LR = 1``, which costs ``log₂(2) = 1`` bit weighted by ``1/(2·N_diff)``. Half a bit is
  therefore the best a corpus with any non-target in it can achieve, and a ``Cllr`` near 0.5 is a
  *perfect* score rather than a mediocre one. ``Cllr_min`` has no such floor: a recalibration is not
  bound by that rule and may map a score band below 1, so the same corpus has ``Cllr_min = 0``.
* **a corpus needs both classes.** With only same-source or only different-source trials every set
  of ratios costs the same, so the number would say nothing while looking like a result. That is
  refused rather than reported.

## `CalibrationCase`

```python
CalibrationCase(case_id: str, truth: GroundTruth, score: float | None = None, refusal: str | None = None, priced: bool = True)
```

One adjudicated claim, with the truth about it recorded separately.

**Attributes**

- `case_id` `str` — what to call it in a report.
- `truth` `GroundTruth` — whether the asserted payment is the one the window holds. **Not** the verdict: a supported claim can be false, and calibrating against verdicts would measure the library against itself.
- `score` `float | None` — ``log10`` of the ratio, or ``None`` when none was reported.
- `refusal` `str | None` — why no ratio was reported, when that is the reason there is none.
- `priced` `bool` — whether a ratio was *expected* at all. ``False`` for a verdict that cannot carry one — a contradiction, by design — so the two ways of having no ratio stay distinct.

**Members**

- `case_id`
- `truth`
- `score` = None
- `refusal` = None
- `priced` = True

## `CalibrationCost`

```python
CalibrationCost(cllr: float, cllr_min: float, calibration_loss: float, same_source: int, different_source: int)
```

The Cllr, the best a recalibration could do, and the gap between them.

**Attributes**

- `cllr` `float` — the average cost in bits of decisions made from these ratios.
- `cllr_min` `float` — the same after the best monotone re-mapping of the scores, which is 0 for a set that ranks perfectly — a recalibration is free to map a band below ``LR = 1``, which the library itself is not.
- `calibration_loss` `float` — ``cllr - cllr_min``. What a recalibration could recover: large means the ratios rank cases well and are on the wrong scale.
- `same_source` `int` — how many same-source trials the cost is over.
- `different_source` `int` — how many different-source trials.

**Members**

- `cllr`
- `cllr_min`
- `calibration_loss`
- `same_source`
- `different_source`

## `CalibrationReport`

```python
CalibrationReport(cases: int, priced: int, refused: int, not_applicable: int, cost: CalibrationCost | None, refusals: dict[str, int] = dict(), warnings: tuple[str, ...] = ())
```

What a corpus of cases came to: the cost, and everything that was not priced.

**Attributes**

- `cases` `int` — how many cases were run.
- `priced` `int` — how many produced a ratio, which is what the cost is computed over.
- `refused` `int` — how many should have produced one and did not, with the reasons counted.
- `not_applicable` `int` — how many could not carry a ratio at all — a contradicted claim cannot, because a ratio is never below 1.
- `cost` `CalibrationCost | None` — the Cllr and its decomposition, or ``None`` when too few cases were priced to compute one.
- `refusals` `dict[str, int]` — refusal reason to count, so a pattern in *why* ratios are missing is visible rather than summarised away.
- `warnings` `tuple[str, ...]` — anything that qualifies the numbers.

**Members**

- `cases`
- `priced`
- `refused`
- `not_applicable`
- `cost`
- `refusals` = field(default_factory=dict)
- `warnings` = ()

### `coverage`

The fraction of *priceable* cases that produced a ratio.

Over priceable cases rather than all of them: a contradicted claim is not a missing ratio,
and counting it as one would make every corpus of mostly-contradicted claims look like a
failure of the estimator.

### `format`

```python
format() -> str
```

A report for a person, with the coverage and the caveats above the number.

## `CalibrationTrial`

```python
CalibrationTrial(score: float, same_source: bool)
```

One case as the metric sees it: a score, and which class it belongs to.

The score is ``log10`` of the ratio, because that is the scale the library reports and the one
the sensitivity envelope is built on. Only the *ordering* matters for `_cllr_min`; the
value matters for the cost itself, since a ratio of 1,000 and one of 10,000 are different
claims about the evidence.

**Members**

- `score`
- `same_source`

## `GroundTruth`

Whether the asserted payment is the one the window holds.

Named for the two classes a likelihood ratio is *between*, not for a verdict: the question a
ratio weighs is "is this the specific payment asserted, or a coincidence by the same sender"
(see ``NullModel``), and calibration asks how well the ratios answer it.

**Members**

- `SAME_SOURCE` = 'same_source'
- `DIFFERENT_SOURCE` = 'different_source'

## `case_from_finding`

```python
case_from_finding(case_id: str, truth: GroundTruth, finding: VerificationFinding) -> CalibrationCase
```

Read one finding as a calibration case.

Three outcomes, and keeping them apart is the point:

* **a ratio was reported** — the trial's score is its logarithm.
* **one was expected and not reported** — a supported verdict with a reason, which is a
  *refusal*: the estimator had something to price and could not.
* **one was not applicable** — anything but a supported verdict. A contradicted claim cannot
  carry a ratio, because a ratio is never below 1, so counting its absence as a refusal would
  blame the estimator for arithmetic.

## `format_report`

```python
format_report(report: CalibrationReport) -> str
```

The report as text, for a tool that prints rather than returns.

## `log_likelihood_ratio_cost`

```python
log_likelihood_ratio_cost(trials: Iterable[CalibrationTrial]) -> CalibrationCost
```

The Cllr of these trials, with the part a recalibration could recover.

**Raises**

- `ValueError` — either class is empty. Every set of ratios costs the same against one class, so the number would look like a result and mean nothing.

## `report_from_cases`

```python
report_from_cases(cases: Sequence[CalibrationCase]) -> CalibrationReport
```

The cost over the cases that produced a ratio, and the account of the ones that did not.
