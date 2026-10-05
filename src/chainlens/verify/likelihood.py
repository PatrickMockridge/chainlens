"""The likelihood ratio for a matched transfer, and how much to trust it.

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
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from enum import StrEnum

from pydantic import Field, model_validator

from chainlens.models.base import LensModel, Provenance
from chainlens.models.enums import VerbalScale
from chainlens.verify.scale import DEFAULT_THRESHOLDS, VerbalBand, VerbalThresholds, band_for

__all__ = [
    "ComponentEstimate",
    "EstimatorMethod",
    "LikelihoodRatio",
    "NullModel",
    "SensitivityReport",
    "Sweep",
    "coincidence_probability",
    "evaluate_likelihood",
    "likelihood_ratio",
    "linearisation_relative_error",
    "sensitivity_report",
    "wilson_interval",
]

#: The z for a 95% interval. Hard-coded rather than pulled from scipy: the whole
#: module is standard-library only so it stays importable everywhere.
_Z_95 = 1.959963984540054

#: Below this many joint successes the interval on `p` spans more than an order of
#: magnitude and no verbal band is defensible.
MIN_JOINT_SUCCESSES = 10


class NullModel(StrEnum):
    """Which coincidence the alternative proposition describes.

    They are genuinely different questions and they are not interchangeable:

    * :attr:`WITHIN_SENDER` — "A did not make the claimed transfer, but one of A's
      *other* transfers coincidentally looks like it". Estimated from A's own
      out-of-window history.
    * :attr:`POPULATION` — "a transfer of this shape is common network-wide".
      Estimated from a background sample of transfers that are not A's.

    Sampling the wrong one errs in a direction that depends on the claim: for a
    busy recipient the population rate overstates `p` (conservative, for the wrong
    reason), while for a recipient that is rare globally but is the sender's sole
    counterparty it understates the sender's own rate and so **overstates the LR**.
    """

    WITHIN_SENDER = "within_sender"
    POPULATION = "population"


class EstimatorMethod(StrEnum):
    """How the coincidence probability was arrived at.

    :attr:`EMPIRICAL_JOINT` counts recipients and amounts *together* and assumes
    nothing. :attr:`FACTORED` multiplies two marginals, which assumes independence
    the data does not support, and is therefore always reported as an upper bound.
    """

    EMPIRICAL_JOINT = "empirical_joint"
    FACTORED = "factored"


def wilson_interval(successes: int, trials: int, *, z: float = _Z_95) -> tuple[float, float]:
    """A Wilson score interval for a binomial proportion.

    Chosen because it is closed-form and behaves sensibly at small `n` and at
    proportions near 0 or 1, where the naive normal interval collapses to a
    zero-width point. A Jeffreys or Clopper-Pearson interval would be the natural
    alternatives and need the inverse incomplete beta function; this module stays
    dependency-free, and the difference at these sample sizes is small.

    Raises:
        ValueError: on a nonsensical count or a non-positive z.
    """
    if trials < 0 or successes < 0:
        raise ValueError(f"counts must be non-negative, got {successes}/{trials}")
    if successes > trials:
        raise ValueError(f"cannot have {successes} successes in {trials} trials")
    if z <= 0:
        raise ValueError(f"z must be positive, got {z}")
    if trials == 0:
        return (0.0, 1.0)  # no information at all

    proportion = successes / trials
    denominator = 1.0 + z * z / trials
    centre = (proportion + z * z / (2 * trials)) / denominator
    spread = (
        z
        * math.sqrt(proportion * (1 - proportion) / trials + z * z / (4 * trials * trials))
        / denominator
    )
    lower = centre - spread
    upper = centre + spread

    # When every trial fails, or every trial succeeds, the formula's endpoint is
    # exactly 0 or 1 -- the two terms cancel. Floating point leaves roughly 1e-18
    # behind instead, which is not a bound any sample supports and would make "no
    # matches observed" look like a tiny non-zero rate. Round the artefact away.
    if successes == 0:
        lower = 0.0
    if successes == trials:
        upper = 1.0
    return (max(0.0, lower), min(1.0, upper))


def coincidence_probability(k: int, p: float) -> float:
    """`1 - (1-p)^k` — the chance that at least one of `k` opportunities matches.

    Evaluated as `-expm1(k * log1p(-p))` rather than the naive
    `1 - (1 - p) ** k`, which loses all precision to cancellation for the small
    `p` this is usually called with.

    Raises:
        ValueError: if `k` is negative or `p` is outside `[0, 1]`.
    """
    if k < 0:
        raise ValueError(f"a trial count cannot be negative, got {k}")
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"a probability must lie in [0, 1], got {p!r}")
    if k == 0 or p == 0.0:
        return 0.0
    if p == 1.0:
        return 1.0
    return -math.expm1(k * math.log1p(-p))


def likelihood_ratio(k: int, p: float) -> float:
    """`1 / coincidence_probability(k, p)`.

    Always `>= 1`: a match cannot count against the claim it matches. Returns
    `math.inf` for `p = 0`, which is mathematically correct but is **not** a value
    to report — a finite sample cannot establish a zero coincidence probability, so
    the estimator refuses such a case upstream rather than emitting an infinity.
    """
    coincident = coincidence_probability(k, p)
    if coincident == 0.0:
        return math.inf
    return 1.0 / coincident


def linearisation_relative_error(k: int, p: float) -> float:
    """How far `1/(k·p)` is from the truth, as a fraction — for the warning.

    The linearisation's error is the sum of the discarded binomial terms, whose
    leading contribution is about `(k-1)·p/2`. Reported so the code can *say* the
    approximation is being leaned on rather than silently using it.
    """
    if k <= 0 or p <= 0.0:
        return 0.0
    return ((k - 1) * p) / 2.0


class ComponentEstimate(LensModel):
    """A probability estimated from a finite sample, with its interval.

    Carrying `successes` and `trials` rather than only the fitted `value` is what
    makes the statistical sensitivity sweep possible, and it is what lets a reader
    see whether a rate came from 4 observations or 4,000.

    Attributes:
        value: the estimated probability.
        successes: how many observations matched.
        trials: how many were examined.
        ci_lower: lower bound of the confidence interval.
        ci_upper: upper bound.
        method: joint or factored; factored always means an upper bound.
        population: what was sampled, in words, for the report.
        is_upper_bound: whether ``value`` is known to over-state the true rate.
    """

    value: float = Field(ge=0.0, le=1.0)
    successes: int = Field(ge=0)
    trials: int = Field(ge=0)
    ci_lower: float = Field(ge=0.0, le=1.0)
    ci_upper: float = Field(ge=0.0, le=1.0)
    method: EstimatorMethod
    population: str
    is_upper_bound: bool = False

    @model_validator(mode="after")
    def _coherent(self) -> ComponentEstimate:
        if self.successes > self.trials:
            raise ValueError(f"cannot have {self.successes} matches in {self.trials} observations")
        if not self.ci_lower <= self.value <= self.ci_upper:
            raise ValueError(
                f"estimate {self.value} lies outside its own interval "
                f"[{self.ci_lower}, {self.ci_upper}]"
            )
        return self

    @property
    def is_sparse(self) -> bool:
        """Whether the sample is too thin to support a verbal band."""
        return self.successes < MIN_JOINT_SUCCESSES

    @property
    def relative_width(self) -> float:
        """Interval width relative to the estimate — how little the sample pins down."""
        if self.value <= 0:
            return math.inf
        return (self.ci_upper - self.ci_lower) / self.value


class Sweep(LensModel):
    """One perturbation of the inputs, and what it did to the ratio."""

    name: str
    lr: float = Field(ge=0.0)
    verbal: VerbalScale


class SensitivityReport(LensModel):
    """How much the ratio moves when the assumptions are nudged.

    A point likelihood ratio invites more confidence than it has earned, so every
    result carries this. When the interval spans more than one verbal band the
    result is *fragile*, and the headline should be the lower bound rather than the
    point — because the sweep that moved it is a choice we made, not a fact about
    the chain.

    Attributes:
        point_lr: the ratio at the fitted values.
        lower_lr: lower end of the interval.
        upper_lr: upper end.
        confidence: the interval's nominal coverage.
        verbal_point: band at the point estimate.
        verbal_lower: band at the lower bound — the headline when fragile.
        fragile: whether the evidence spans more than one band, or any sweep
            crossed a boundary.
        straddled: every band the interval touches, in scale order.
        sweeps: each named perturbation and its result.
    """

    point_lr: float = Field(ge=0.0)
    lower_lr: float = Field(ge=0.0)
    upper_lr: float = Field(ge=0.0)
    confidence: float = Field(gt=0.0, lt=1.0)
    verbal_point: VerbalScale
    verbal_lower: VerbalScale
    fragile: bool
    straddled: tuple[VerbalScale, ...] = ()
    sweeps: tuple[Sweep, ...] = ()

    @property
    def headline_band(self) -> VerbalScale:
        """The band to lead with: the conservative one when the result is fragile."""
        return self.verbal_lower if self.fragile else self.verbal_point


class LikelihoodRatio(LensModel):
    """The evidential weight of a matched transfer, with everything it rests on.

    ``assumptions`` and ``caveats`` are mandatory and validator-enforced, mirroring
    the investigation report's mandatory methodology: a bare number with no record
    of what it assumed is exactly the artefact this whole design works to avoid.

    Attributes:
        k: the sender's transfer count in the window.
        p: the coincidence probability.
        lr: the likelihood ratio.
        log10_lr: its base-10 logarithm, the scale these are usually read on.
        verbal: the ratio placed on the ENFSI scale.
        null_model: which coincidence the alternative proposition describes.
        components: the estimates `p` was built from.
        sensitivity: how much the ratio moves under perturbation.
        p_is_upper_bound: whether `p` is known to be too high, making `lr` too low.
        assumptions: what had to be true.
        caveats: what the number does not cover.
        provenance: where the underlying data came from.
    """

    k: int = Field(ge=0)
    p: float = Field(ge=0.0, le=1.0)
    lr: float = Field(ge=0.0)
    log10_lr: float | None = None
    verbal: VerbalBand
    null_model: NullModel
    components: tuple[ComponentEstimate, ...] = ()
    sensitivity: SensitivityReport
    p_is_upper_bound: bool = False
    assumptions: tuple[str, ...]
    caveats: tuple[str, ...]
    provenance: tuple[Provenance, ...] = ()

    @model_validator(mode="after")
    def _must_state_its_terms(self) -> LikelihoodRatio:
        if not self.assumptions:
            raise ValueError(
                "a likelihood ratio must record the assumptions it rests on; an "
                "unqualified number cannot be evaluated"
            )
        if not self.caveats:
            raise ValueError(
                "a likelihood ratio must state what it does not cover; without that "
                "it reads as a statement about the claim rather than about one match"
            )
        if self.lr < 1.0 and not math.isclose(self.lr, 1.0):
            raise ValueError(
                f"a matched transfer cannot count against the claim, yet lr={self.lr}; "
                "this indicates a sign or reciprocal error upstream"
            )
        return self

    def with_prior_log_odds(self, prior_log_odds: float) -> float:
        """Posterior log-odds, given the caller's own prior log-odds.

        Deliberately takes log-odds rather than a probability so the caller has to
        have thought about the number they are supplying. The library ships no
        default and will not choose one for you.
        """
        if not math.isfinite(prior_log_odds):
            raise ValueError(f"prior log-odds must be finite, got {prior_log_odds!r}")
        if self.log10_lr is None:
            raise ValueError("cannot update a ratio that has no logarithm")
        return prior_log_odds + self.log10_lr * math.log(10.0)

    def posterior_probability(self, prior: float) -> float:
        """Posterior probability, given a **caller-supplied** prior probability.

        Raises:
            ValueError: if the prior is not strictly inside ``(0, 1)``. A prior of
                exactly 0 or 1 cannot be moved by any evidence, which is almost
                always a mistake rather than a belief.
        """
        if not 0.0 < prior < 1.0:
            raise ValueError(
                f"a prior must lie strictly between 0 and 1 to be updatable, got {prior!r}"
            )
        prior_log_odds = math.log(prior / (1.0 - prior))
        posterior_log_odds = self.with_prior_log_odds(prior_log_odds)
        odds = math.exp(posterior_log_odds)
        return odds / (1.0 + odds)


def _beta_sample(alpha: float, beta: float, rng: random.Random) -> float:
    """Draw from Beta(alpha, beta) using two gamma variates.

    Standard-library only, which is why it is written out: the alternative is a
    numerics dependency for one function.
    """
    left = rng.gammavariate(alpha, 1.0)
    right = rng.gammavariate(beta, 1.0)
    total = left + right
    return 0.5 if total <= 0 else left / total


def _quantile(values: Sequence[float], fraction: float) -> float:
    """Linear-interpolated quantile of an already-sorted sequence."""
    if not values:
        return 0.0
    position = fraction * (len(values) - 1)
    lower = math.floor(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def sensitivity_report(
    *,
    k: int,
    component: ComponentEstimate,
    variants: Mapping[str, float] | None = None,
    k_permutations: Sequence[int] = (),
    thresholds: VerbalThresholds = DEFAULT_THRESHOLDS,
    draws: int = 2_000,
    seed: int = 0,
    confidence: float = 0.95,
) -> SensitivityReport:
    """Perturb the inputs and report how far the ratio moves.

    Five sweeps from the plan collapse to three here because two of them are the
    caller's to run: the **tolerance** sweep needs the sample to recount the joint
    at a different band, and the **reference population** sweep needs a second
    sample. Both arrive as ``variants``, so the pure core stays pure and the
    sampler owns the fetching.

    Args:
        k: the sender's transfer count.
        component: the coincidence probability and its sample.
        variants: named alternative values of `p`, from tolerance or population
            sweeps run by the caller.
        k_permutations: alternative counts, for the coverage sweep.
        draws: Monte-Carlo draws for the statistical sweep.
        seed: RNG seed. Fixed by default so a report is reproducible.
    """
    if draws < 1:
        raise ValueError(f"draws must be positive, got {draws}")
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must lie in (0, 1), got {confidence}")

    point = likelihood_ratio(k, component.value)
    rng = random.Random(seed)

    # Jeffreys prior on the joint rate, so a zero count still yields a usable
    # interval rather than collapsing to a point at zero.
    alpha = component.successes + 0.5
    beta = component.trials - component.successes + 0.5
    sampled = sorted(likelihood_ratio(k, _beta_sample(alpha, beta, rng)) for _ in range(draws))
    tail = (1.0 - confidence) / 2.0
    lower = _quantile(sampled, tail)
    upper = _quantile(sampled, 1.0 - tail)

    sweeps: list[Sweep] = []
    for name, alternative in (variants or {}).items():
        ratio = likelihood_ratio(k, alternative)
        sweeps.append(Sweep(name=f"p:{name}", lr=ratio, verbal=band_for(ratio, thresholds).scale))
    for alternative_k in k_permutations:
        ratio = likelihood_ratio(alternative_k, component.value)
        sweeps.append(
            Sweep(name=f"k:{alternative_k}", lr=ratio, verbal=band_for(ratio, thresholds).scale)
        )

    bands = {band_for(value, thresholds).scale for value in (point, lower, upper)}
    bands.update(sweep.verbal for sweep in sweeps)
    straddled = tuple(sorted(bands, key=lambda scale: scale.rank))
    fragile = len(straddled) > 1

    return SensitivityReport(
        point_lr=point,
        lower_lr=lower,
        upper_lr=upper,
        confidence=confidence,
        verbal_point=band_for(point, thresholds).scale,
        verbal_lower=band_for(lower, thresholds).scale,
        fragile=fragile,
        straddled=straddled,
        sweeps=tuple(sweeps),
    )


def evaluate_likelihood(
    *,
    k: int,
    component: ComponentEstimate,
    null_model: NullModel,
    variants: Mapping[str, float] | None = None,
    k_permutations: Sequence[int] = (),
    thresholds: VerbalThresholds = DEFAULT_THRESHOLDS,
    draws: int = 2_000,
    seed: int = 0,
    provenance: Sequence[Provenance] = (),
) -> LikelihoodRatio:
    """Assemble the full ratio from a counted `k` and an estimated `p`.

    Raises:
        ValueError: if `k` is zero — with no opportunities there is no coincidence
            to price, and the honest answer is a categorical finding rather than a
            ratio of 1 dressed up as a weak result.
    """
    if k <= 0:
        raise ValueError(
            "a sender with no transfers in the window offers no opportunity for a "
            "coincidence; there is no ratio to compute, only a categorical finding"
        )

    p = component.value
    ratio = likelihood_ratio(k, p)
    report = sensitivity_report(
        k=k,
        component=component,
        variants=variants,
        k_permutations=k_permutations,
        thresholds=thresholds,
        draws=draws,
        seed=seed,
    )

    assumptions = [
        "the sender's transfers in the window were indexed exhaustively, which is "
        "what licenses P(match | first proposition) = 1",
        "the claim's identifiers were extracted correctly; extraction error is not "
        "modelled and every figure here is conditional on it",
    ]
    if component.method is EstimatorMethod.FACTORED:
        assumptions.append(
            "recipient and amount were treated as independent, which the data does "
            "not support; p is therefore an upper bound and the ratio a lower bound"
        )
    if component.is_sparse:
        assumptions.append(
            f"the coincidence rate rests on only {component.successes} joint "
            f"observations out of {component.trials}"
        )

    caveats = [
        "this is the weight of one matched transfer, not the probability that the "
        "claim is true; going from one to the other needs a prior, which this "
        "library does not supply",
        "it measures whether the observed transfer is the specific payment "
        "asserted rather than a coincidence, not whether the sender was named "
        "correctly",
        "it cannot correct for how the claim was chosen; a sender and an amount "
        "picked to look unusual will score well",
    ]
    if report.fragile:
        caveats.append(
            "the result is fragile: plausible variation moves it across a verbal "
            "boundary, so read the lower bound rather than the point"
        )

    log10_lr = math.inf if math.isinf(ratio) else math.log10(ratio)

    return LikelihoodRatio(
        k=k,
        p=p,
        lr=ratio,
        log10_lr=log10_lr,
        verbal=band_for(ratio, thresholds),
        null_model=null_model,
        components=(component,),
        sensitivity=report,
        p_is_upper_bound=component.is_upper_bound,
        assumptions=tuple(assumptions),
        caveats=tuple(caveats),
        provenance=tuple(provenance),
    )
