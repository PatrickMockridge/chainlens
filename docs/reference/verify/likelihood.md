# `chainlens.verify.likelihood`

The likelihood ratio for a matched transfer, and how much to trust it.

The model is the forensic **database-search correction**. When a match is found by
searching a space of size `N` rather than by prior suspicion, the classic result
(NRC II; Stockmarr 1999) is `LR = 1/(N·p)`. Here `k` — the transfers the sender
actually made in the window — *is* that search space, and `p` is the chance that
one of them matches the claim by coincidence:

    P(E | first proposition, complete scan) = 1
    P(E | alternative proposition)          = 1 - (1 - p)^k
    LR                                      = 1 / (1 - (1 - p)^k)

Three properties of that formula drive everything else in this module.

**The exact form ships; the linearisation does not.** `1/(k·p)` is the familiar
approximation and it is wrong where it matters — at `p = 1` it returns `1/k` where
the truth is `1`, turning "no evidence at all" into "weak evidence".

**The ratio is never below 1.** `1 - (1-p)^k <= 1`, so finding a match can never
count against the claim. That is correct — the evidence *is* the match — and it
means the band always supports the first proposition or neither.

**The number is not a probability.** It is the weight of one piece of evidence, and
converting it into a probability requires a prior this library deliberately does
not supply. See `docs` for why.

What the ratio measures is also narrower than "the claim is true": a coincidental
match would satisfy the literal proposition, so the two hypotheses only separate if
the first is read as *the specific payment the poster meant*. The ratio is evidence
that the observed transfer is that payment rather than a coincidence — not that the
sender was named correctly, which is a commoner error and one no on-chain data can
settle.

## `ComponentEstimate`

A probability estimated from a finite sample, with its interval.

Carrying `successes` and `trials` rather than only the fitted `value` is what
makes the statistical sensitivity sweep possible, and it is what lets a reader
see whether a rate came from 4 observations or 4,000.

**Attributes**

- `value` `float` — the estimated probability.
- `successes` `int` — how many observations matched.
- `trials` `int` — how many were examined.
- `ci_lower` `float` — lower bound of the confidence interval.
- `ci_upper` `float` — upper bound.
- `method` `EstimatorMethod` — joint or factored; factored always means an upper bound.
- `population` `str` — what was sampled, in words, for the report.
- `is_upper_bound` `bool` — whether ``value`` is known to over-state the true rate.

**Members**

- `value` = Field(ge=0.0, le=1.0)
- `successes` = Field(ge=0)
- `trials` = Field(ge=0)
- `ci_lower` = Field(ge=0.0, le=1.0)
- `ci_upper` = Field(ge=0.0, le=1.0)
- `method`
- `population`
- `is_upper_bound` = False

### `is_sparse`

Whether the sample is too thin to support a verbal band.

### `relative_width`

Interval width relative to the estimate — how little the sample pins down.

## `EstimatorMethod`

How the coincidence probability was arrived at.

`EMPIRICAL_JOINT` counts recipients and amounts *together* and assumes
nothing. `FACTORED` multiplies two marginals, which assumes independence
the data does not support, and is therefore always reported as an upper bound.

**Members**

- `EMPIRICAL_JOINT` = 'empirical_joint'
- `FACTORED` = 'factored'

## `LikelihoodRatio`

The evidential weight of a matched transfer, with everything it rests on.

``assumptions`` and ``caveats`` are mandatory and validator-enforced, mirroring
the investigation report's mandatory methodology: a bare number with no record
of what it assumed is exactly the artefact this whole design works to avoid.

**Attributes**

- `k` `int` — the sender's transfer count in the window.
- `p` `float` — the coincidence probability.
- `lr` `float` — the likelihood ratio.
- `log10_lr` `float | None` — its base-10 logarithm, the scale these are usually read on.
- `verbal` `VerbalBand` — the ratio placed on the ENFSI scale.
- `null_model` `NullModel` — which coincidence the alternative proposition describes.
- `components` `tuple[ComponentEstimate, ...]` — the estimates `p` was built from.
- `sensitivity` `SensitivityReport` — how much the ratio moves under perturbation.
- `p_is_upper_bound` `bool` — whether `p` is known to be too high, making `lr` too low.
- `assumptions` `tuple[str, ...]` — what had to be true.
- `caveats` `tuple[str, ...]` — what the number does not cover.
- `provenance` `tuple[Provenance, ...]` — where the underlying data came from.

**Members**

- `k` = Field(ge=0)
- `p` = Field(ge=0.0, le=1.0)
- `lr` = Field(ge=0.0)
- `log10_lr` = None
- `verbal`
- `null_model`
- `components` = ()
- `sensitivity`
- `p_is_upper_bound` = False
- `assumptions`
- `caveats`
- `provenance` = ()

### `with_prior_log_odds`

```python
with_prior_log_odds(prior_log_odds: float) -> float
```

Posterior log-odds, given the caller's own prior log-odds.

Deliberately takes log-odds rather than a probability so the caller has to
have thought about the number they are supplying. The library ships no
default and will not choose one for you.

### `posterior_probability`

```python
posterior_probability(prior: float) -> float
```

Posterior probability, given a **caller-supplied** prior probability.

**Raises**

- `ValueError` — if the prior is not strictly inside ``(0, 1)``. A prior of exactly 0 or 1 cannot be moved by any evidence, which is almost always a mistake rather than a belief.

## `NullModel`

Which coincidence the alternative proposition describes.

They are genuinely different questions and they are not interchangeable:

* `WITHIN_SENDER` — "A did not make the claimed transfer, but one of A's
  *other* transfers coincidentally looks like it". Estimated from A's own
  out-of-window history.
* `POPULATION` — "a transfer of this shape is common network-wide".
  Estimated from a background sample of transfers that are not A's.

Sampling the wrong one errs in a direction that depends on the claim: for a
busy recipient the population rate overstates `p` (conservative, for the wrong
reason), while for a recipient that is rare globally but is the sender's sole
counterparty it understates the sender's own rate and so **overstates the LR**.

**Members**

- `WITHIN_SENDER` = 'within_sender'
- `POPULATION` = 'population'

## `SensitivityReport`

How much the ratio moves when the assumptions are nudged.

A point likelihood ratio invites more confidence than it has earned, so every
result carries this. When the interval spans more than one verbal band the
result is *fragile*, and the headline should be the lower bound rather than the
point — because the sweep that moved it is a choice we made, not a fact about
the chain.

**Attributes**

- `point_lr` `float` — the ratio at the fitted values.
- `lower_lr` `float` — lower end of the interval.
- `upper_lr` `float` — upper end.
- `confidence` `float` — the interval's nominal coverage.
- `verbal_point` `VerbalScale` — band at the point estimate.
- `verbal_lower` `VerbalScale` — band at the lower bound — the headline when fragile.
- `fragile` `bool` — whether the evidence spans more than one band, or any sweep crossed a boundary.
- `straddled` `tuple[VerbalScale, ...]` — every band the interval touches, in scale order.
- `sweeps` `tuple[Sweep, ...]` — each named perturbation and its result.

**Members**

- `point_lr` = Field(ge=0.0)
- `lower_lr` = Field(ge=0.0)
- `upper_lr` = Field(ge=0.0)
- `confidence` = Field(gt=0.0, lt=1.0)
- `verbal_point`
- `verbal_lower`
- `fragile`
- `straddled` = ()
- `sweeps` = ()

### `headline_band`

The band to lead with: the conservative one when the result is fragile.

## `Sweep`

One perturbation of the inputs, and what it did to the ratio.

**Members**

- `name`
- `lr` = Field(ge=0.0)
- `verbal`

## `MIN_JOINT_SUCCESSES`

## `coincidence_probability`

```python
coincidence_probability(k: int, p: float) -> float
```

`1 - (1-p)^k` — the chance that at least one of `k` opportunities matches.

Evaluated as `-expm1(k * log1p(-p))` rather than the naive
`1 - (1 - p) ** k`, which loses all precision to cancellation for the small
`p` this is usually called with.

**Raises**

- `ValueError` — if `k` is negative or `p` is outside `[0, 1]`.

## `evaluate_likelihood`

```python
evaluate_likelihood(*, k: int, component: ComponentEstimate, null_model: NullModel, variants: Mapping[str, float] | None = None, k_permutations: Sequence[int] = (), thresholds: VerbalThresholds = DEFAULT_THRESHOLDS, draws: int = 2000, seed: int = 0, provenance: Sequence[Provenance] = ()) -> LikelihoodRatio
```

Assemble the full ratio from a counted `k` and an estimated `p`.

**Raises**

- `ValueError` — if `k` is zero — with no opportunities there is no coincidence to price, and the honest answer is a categorical finding rather than a ratio of 1 dressed up as a weak result.

## `formula_for`

```python
formula_for(kind: OperationKind) -> str
```

The expression an operation performs, for display on an artifact.

The formula lives here, beside the functions that compute the numbers, rather than in a renderer
or a document builder. There is one home for it, so a change to the arithmetic and a change to
what the artifact says it does are changes to the same file.

**It is the definition, not the evaluation.** These are computed in algebraically identical but
numerically stabler forms — `coincidence_probability` uses ``-expm1(k * log1p(-p))``
because the naive form loses all its precision to cancellation for the small ``p`` this is
usually called with. So the displayed formula and the computed value agree to floating-point
error rather than bit for bit, and the test holding them together allows exactly that much. A
reader who recomputes ``1 - (1 - p) ** k`` by hand gets the same number to every digit they are
likely to write down, and the artifact is not claiming more than that.

The posterior is written in terms of the ratio and the prior directly — ``odds / (1 + odds)``
with ``odds = lr * prior / (1 - prior)`` cancels to this — so that every symbol is an input the
artifact carries rather than an intermediate a reader has to reconstruct.

## `likelihood_ratio`

```python
likelihood_ratio(k: int, p: float) -> float
```

`1 / coincidence_probability(k, p)`.

Always `>= 1`: a match cannot count against the claim it matches. Returns
`math.inf` for `p = 0`, which is mathematically correct but is **not** a value
to report — a finite sample cannot establish a zero coincidence probability, so
the estimator refuses such a case upstream rather than emitting an infinity.

## `linearisation_relative_error`

```python
linearisation_relative_error(k: int, p: float) -> float
```

How far `1/(k·p)` is from the truth, as a fraction — for the warning.

The linearisation's error is the sum of the discarded binomial terms, whose
leading contribution is about `(k-1)·p/2`. Reported so the code can *say* the
approximation is being leaned on rather than silently using it.

## `sensitivity_report`

```python
sensitivity_report(*, k: int, component: ComponentEstimate, variants: Mapping[str, float] | None = None, k_permutations: Sequence[int] = (), thresholds: VerbalThresholds = DEFAULT_THRESHOLDS, draws: int = 2000, seed: int = 0, confidence: float = 0.95) -> SensitivityReport
```

Perturb the inputs and report how far the ratio moves.

Five sweeps from the plan collapse to three here because two of them are the
caller's to run: the **tolerance** sweep needs the sample to recount the joint
at a different band, and the **reference population** sweep needs a second
sample. Both arrive as ``variants``, so the pure core stays pure and the
sampler owns the fetching.

**Parameters**

- `k` `int` — the sender's transfer count.
- `component` `ComponentEstimate` — the coincidence probability and its sample.
- `variants` `Mapping[str, float] | None`, default `None` — named alternative values of `p`, from tolerance or population sweeps run by the caller.
- `k_permutations` `Sequence[int]`, default `()` — alternative counts, for the coverage sweep.
- `draws` `int`, default `2000` — Monte-Carlo draws for the statistical sweep.
- `seed` `int`, default `0` — RNG seed. Fixed by default so a report is reproducible.

## `wilson_interval`

```python
wilson_interval(successes: int, trials: int, *, z: float = _Z_95) -> tuple[float, float]
```

A Wilson score interval for a binomial proportion.

Chosen because it is closed-form and behaves sensibly at small `n` and at
proportions near 0 or 1, where the naive normal interval collapses to a
zero-width point. A Jeffreys or Clopper-Pearson interval would be the natural
alternatives and need the inverse incomplete beta function; this module stays
dependency-free, and the difference at these sample sizes is small.

**Raises**

- `ValueError` — on a nonsensical count or a non-positive z.
