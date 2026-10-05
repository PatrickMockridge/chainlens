"""The likelihood-ratio maths, the verbal scale, and the claim elements.

The two tests that matter most are the ones pinning errors this module was
written *after* making: that `p = 1` gives a ratio of exactly 1 rather than `1/k`,
and that a matched transfer can never produce a ratio below 1. Both are easy to get
wrong and neither looks wrong in output.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from chainlens.models.enums import Chain, Proposition, VerbalScale
from chainlens.models.primitives import AssetRef
from chainlens.verify import (
    ActivityWindow,
    AmountBand,
    ClaimElements,
    ComponentEstimate,
    EstimatorMethod,
    LikelihoodRatio,
    NullModel,
    band_for,
    coincidence_probability,
    evaluate_likelihood,
    likelihood_ratio,
    linearisation_relative_error,
    sensitivity_report,
    wilson_interval,
)
from chainlens.verify.scale import VerbalThresholds

PROBABILITY = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
COUNT = st.integers(min_value=0, max_value=5_000)


# --------------------------------------------------------------------------- #
# The verbal scale
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("lr", "expected"),
    [
        (1.0, VerbalScale.NONE),
        (1.0000001, VerbalScale.SLIGHT),
        (10.0, VerbalScale.SLIGHT),
        (10.0001, VerbalScale.MODERATE),
        (100.0, VerbalScale.MODERATE),
        (100.0001, VerbalScale.MODERATELY_STRONG),
        (1_000.0, VerbalScale.MODERATELY_STRONG),
        (1_000.0001, VerbalScale.STRONG),
        (10_000.0, VerbalScale.STRONG),
        (10_000.0001, VerbalScale.VERY_STRONG),
    ],
)
def test_band_boundaries_match_the_enfsi_appendix(lr: float, expected: VerbalScale) -> None:
    """Read off the guideline's own table, not from a summary of it."""
    assert band_for(lr).scale is expected


def test_an_lr_of_one_supports_neither_proposition() -> None:
    band = band_for(1.0)
    assert band.scale is VerbalScale.NONE
    assert band.supports is Proposition.NEITHER
    assert not band.is_informative


def test_the_scale_is_symmetric_for_an_lr_below_one() -> None:
    """An LR below 1 supports the *alternative*, with the band read off its reciprocal."""
    band = band_for(1 / 500)
    assert band.scale is VerbalScale.MODERATELY_STRONG
    assert band.supports is Proposition.ALTERNATIVE
    assert band.ratio == pytest.approx(500.0)


def test_an_lr_above_one_supports_the_first_proposition() -> None:
    band = band_for(500.0)
    assert band.supports is Proposition.FIRST
    assert band.is_informative


def test_an_infinite_lr_lands_in_the_top_band() -> None:
    got = band_for(math.inf)
    assert got.scale is VerbalScale.VERY_STRONG
    assert got.supports is Proposition.FIRST


def test_a_zero_lr_is_handled_rather_than_dividing_by_zero() -> None:
    got = band_for(0.0)
    assert got.supports is Proposition.ALTERNATIVE
    assert got.ratio == math.inf


@pytest.mark.parametrize("bad", [-1.0, -0.001, math.nan])
def test_a_nonsense_lr_is_rejected(bad: float) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        band_for(bad)


@given(st.floats(min_value=1.0, max_value=1e9, allow_nan=False, allow_infinity=False))
def test_banding_is_monotone_on_the_side_the_ratio_supports(lr: float) -> None:
    """More evidence never means a weaker band.

    Monotone in the ratio *only above 1*. The scale is symmetric, so support grows
    with distance from 1 in either direction, and comparing two ratios below 1
    would invert the ordering rather than test it.
    """
    assert band_for(lr).scale.rank <= band_for(lr * 1.5 + 0.001).scale.rank


@given(st.floats(min_value=1.0, max_value=1e9, allow_nan=False, allow_infinity=False))
def test_banding_is_monotone_on_the_alternative_side_too(reciprocal: float) -> None:
    """By symmetry, support for the alternative grows as its ratio grows."""
    weaker = band_for(1.0 / reciprocal).scale.rank
    stronger = band_for(1.0 / (reciprocal * 1.5 + 0.001)).scale.rank
    assert weaker <= stronger


def test_thresholds_must_be_strictly_increasing() -> None:
    with pytest.raises(ValidationError, match="strictly increasing"):
        VerbalThresholds(slight=100.0, moderate=10.0)


def test_thresholds_must_exceed_one() -> None:
    """A band reaching down to 1 would have no lower edge."""
    with pytest.raises(ValidationError):
        VerbalThresholds(slight=1.0)


def test_custom_thresholds_change_the_bands() -> None:
    """Boundaries are institution-dependent, so they must be overridable."""
    strict = VerbalThresholds(slight=2.0, moderate=4.0, moderately_strong=6.0, strong=8.0)
    assert band_for(5.0, strict).scale is VerbalScale.MODERATELY_STRONG
    assert band_for(5.0).scale is VerbalScale.SLIGHT


# --------------------------------------------------------------------------- #
# The maths
# --------------------------------------------------------------------------- #
def test_coincidence_probability_agrees_with_a_hand_computation() -> None:
    # 1 - 0.99^10 = 0.09561792499...
    assert coincidence_probability(10, 0.01) == pytest.approx(0.09561792499, abs=1e-11)


def test_coincidence_probability_of_no_opportunities_is_zero() -> None:
    assert coincidence_probability(0, 0.5) == 0.0


def test_coincidence_probability_of_an_impossible_match_is_zero() -> None:
    assert coincidence_probability(100, 0.0) == 0.0


def test_coincidence_probability_of_a_certain_match_is_one() -> None:
    assert coincidence_probability(100, 1.0) == 1.0


def test_the_p_equals_one_case_gives_a_ratio_of_exactly_one() -> None:
    """Regression: this is `1`, NOT `1/k`.

    The familiar linearisation `1/(k·p)` returns `1/k` here, which reports
    evidential weight where there is none — the whole reason the exact form ships
    and the approximation is only ever mentioned as a caveat.
    """
    assert likelihood_ratio(10, 1.0) == 1.0
    assert likelihood_ratio(1_000, 1.0) == 1.0
    assert likelihood_ratio(10, 1.0) != pytest.approx(0.1)


def test_a_zero_coincidence_probability_is_infinite() -> None:
    """Mathematically correct, and the estimator refuses it upstream."""
    assert likelihood_ratio(10, 0.0) == math.inf


def test_the_exact_form_beats_the_linearisation_at_scale() -> None:
    """They agree only while k·p is small, which is what the error term measures."""
    exact = likelihood_ratio(10, 0.5)
    assert exact == pytest.approx(1 / (1 - 0.5**10))
    assert linearisation_relative_error(10, 0.5) > 0.1


@given(COUNT, PROBABILITY)
def test_coincidence_probability_is_a_probability(k: int, p: float) -> None:
    assert 0.0 <= coincidence_probability(k, p) <= 1.0


@given(COUNT, PROBABILITY)
def test_a_match_never_counts_against_the_claim(k: int, p: float) -> None:
    """The evidence is the match, so the ratio can never fall below 1."""
    if k == 0 or p == 0.0:
        return
    assert likelihood_ratio(k, p) >= 1.0


@given(PROBABILITY)
def test_coincidence_is_monotone_in_the_opportunity_count(p: float) -> None:
    values = [coincidence_probability(k, p) for k in range(0, 40)]
    assert values == sorted(values)


@given(COUNT)
def test_coincidence_is_monotone_in_the_match_rate(k: int) -> None:
    values = [coincidence_probability(k, i / 50) for i in range(51)]
    assert values == sorted(values)


@given(st.integers(1, 5_000), st.floats(min_value=1e-18, max_value=1e-6, allow_nan=False))
def test_the_stable_form_tracks_the_analytic_limit_within_the_known_error(k: int, p: float) -> None:
    """`expm1`/`log1p` earn their place here.

    `k·p` is the leading term of the series, not the answer: the discarded terms
    are relative order `(k-1)p/2`, which is exactly what
    :func:`linearisation_relative_error` reports. The exact form should sit inside
    that bound — and that bound is the same one that decides when it is honest to
    mention `1/(k·p)` at all.
    """
    expected = k * p
    if expected == 0.0:
        return
    bound = max(1e-12, 3.0 * linearisation_relative_error(k, p))
    assert abs(coincidence_probability(k, p) - expected) / expected <= bound


@given(st.integers(1, 200), st.floats(min_value=1e-3, max_value=0.5, allow_nan=False))
def test_the_stable_form_agrees_with_the_series_where_cancellation_is_mild(
    k: int, p: float
) -> None:
    """Away from the cancellation regime the two forms agree, as they must.

    Where they *disagree* is the whole reason the stable form ships. At
    `k = 23, p ≈ 3e-15` the naive `1 - (1-p)**k` returns ~7.15e-14 where the truth
    is ~7.05e-14 -- subtracting a number very close to 1 from 1 throws away most of
    the significant digits, and it is the approximation that is wrong, not this.
    """
    assert coincidence_probability(k, p) == pytest.approx(1 - (1 - p) ** k, rel=1e-9)


@pytest.mark.parametrize(("k", "p"), [(-1, 0.5), (10, -0.1), (10, 1.1)])
def test_impossible_inputs_are_rejected(k: int, p: float) -> None:
    with pytest.raises(ValueError, match=r"cannot be negative|must lie in"):
        coincidence_probability(k, p)


# --------------------------------------------------------------------------- #
# Wilson intervals
# --------------------------------------------------------------------------- #
def test_a_wilson_interval_brackets_the_estimate() -> None:
    lower, upper = wilson_interval(50, 100)
    assert lower < 0.5 < upper


def test_a_wilson_interval_does_not_collapse_at_zero() -> None:
    """Unlike the naive normal interval, which gives a zero-width point here."""
    lower, upper = wilson_interval(0, 50)
    assert lower == 0.0
    assert upper > 0.0


def test_no_observations_means_no_information() -> None:
    assert wilson_interval(0, 0) == (0.0, 1.0)


@pytest.mark.parametrize(("successes", "trials"), [(11, 10), (-1, 10), (0, -1)])
def test_incoherent_counts_are_rejected(successes: int, trials: int) -> None:
    with pytest.raises(ValueError, match=r"must be non-negative|cannot have"):
        wilson_interval(successes, trials)


# --------------------------------------------------------------------------- #
# Component estimates
# --------------------------------------------------------------------------- #
def _component(
    successes: int = 10, trials: int = 100_000, **overrides: object
) -> ComponentEstimate:
    lower, upper = wilson_interval(successes, trials)
    payload: dict[str, object] = {
        "value": successes / trials,
        "successes": successes,
        "trials": trials,
        "ci_lower": lower,
        "ci_upper": upper,
        "method": EstimatorMethod.EMPIRICAL_JOINT,
        "population": "100k transfers in the window, sender cluster excluded",
    }
    payload.update(overrides)
    return ComponentEstimate(**payload)  # type: ignore[arg-type]


def test_an_estimate_outside_its_own_interval_is_rejected() -> None:
    with pytest.raises(ValidationError, match="outside its own interval"):
        _component(ci_lower=0.5, ci_upper=0.9)


def test_more_matches_than_observations_is_rejected() -> None:
    """Constructed directly: the fixture helper computes an interval, which
    rejects the incoherent count before the model gets a chance to."""
    with pytest.raises(ValidationError, match="cannot have"):
        ComponentEstimate(
            value=0.5,
            successes=5,
            trials=3,
            ci_lower=0.0,
            ci_upper=1.0,
            method=EstimatorMethod.EMPIRICAL_JOINT,
            population="nonsense",
        )


def test_sparsity_is_reported() -> None:
    assert _component(successes=3, trials=10_000).is_sparse
    assert not _component(successes=10, trials=10_000).is_sparse


# --------------------------------------------------------------------------- #
# Assembling the ratio
# --------------------------------------------------------------------------- #
def _ratio(**overrides: object) -> LikelihoodRatio:
    payload: dict[str, object] = {
        "k": 20,
        "component": _component(),
        "null_model": NullModel.WITHIN_SENDER,
    }
    payload.update(overrides)
    return evaluate_likelihood(**payload)  # type: ignore[arg-type]


def test_a_ratio_records_what_it_assumed() -> None:
    """A bare number with no record of its terms is the artefact to avoid."""
    ratio = _ratio()
    assert ratio.assumptions
    assert ratio.caveats
    assert any("not the probability" in caveat for caveat in ratio.caveats)


def test_a_ratio_cannot_be_constructed_without_its_terms() -> None:
    ratio = _ratio()
    with pytest.raises(ValidationError, match="assumptions"):
        LikelihoodRatio(**{**ratio.model_dump(), "assumptions": ()})
    with pytest.raises(ValidationError, match="does not cover"):
        LikelihoodRatio(**{**ratio.model_dump(), "caveats": ()})


def test_a_ratio_below_one_is_structurally_rejected() -> None:
    """A matched transfer cannot count against the claim, so this is a bug signal."""
    ratio = _ratio()
    with pytest.raises(ValidationError, match="cannot count against"):
        LikelihoodRatio(**{**ratio.model_dump(), "lr": 0.5})


def test_a_sender_with_no_opportunities_is_refused() -> None:
    with pytest.raises(ValueError, match="no opportunity"):
        _ratio(k=0)


def test_the_worked_example_matches_a_hand_computation() -> None:
    ratio = _ratio(k=412, component=_component(successes=1, trials=412))
    expected_p = 1 / 412
    assert ratio.lr == pytest.approx(likelihood_ratio(412, expected_p))
    assert ratio.log10_lr == pytest.approx(math.log10(ratio.lr))


# --------------------------------------------------------------------------- #
# Sensitivity
# --------------------------------------------------------------------------- #
def test_a_fragile_result_is_headlined_by_its_lower_bound() -> None:
    """The headline must not be the optimistic end of a range."""
    component = _component(successes=10, trials=100_000)
    report = sensitivity_report(
        k=20,
        component=component,
        # A different null model moves the ratio across the strong boundary, which
        # is exactly what this sweep exists to expose.
        variants={"population null": component.value * 0.4},
        draws=500,
    )
    assert report.fragile
    assert report.headline_band is report.verbal_lower
    assert report.verbal_lower.rank <= report.verbal_point.rank


def test_a_clean_result_headlines_its_point() -> None:
    component = _component(successes=5_000, trials=100_000)
    report = sensitivity_report(k=20, component=component, draws=500)
    if not report.fragile:
        assert report.headline_band is report.verbal_point


def test_the_sweeps_record_what_moved_the_answer() -> None:
    component = _component(successes=10, trials=100_000)
    report = sensitivity_report(
        k=20,
        component=component,
        variants={"tolerance x5": component.value * 5, "population null": component.value * 0.4},
        k_permutations=(19, 21),
        draws=200,
    )
    names = {sweep.name for sweep in report.sweeps}
    assert names == {"p:tolerance x5", "p:population null", "k:19", "k:21"}


def test_a_different_null_can_change_the_verdict() -> None:
    """The point of sweeping it: the choice of null is ours, not the chain's."""
    component = _component(successes=10, trials=100_000)
    report = sensitivity_report(
        k=20, component=component, variants={"population null": component.value * 0.4}, draws=200
    )
    assert report.fragile


def test_sensitivity_is_reproducible() -> None:
    """A report has to be re-derivable, so the RNG is seeded."""
    component = _component()
    first = sensitivity_report(k=20, component=component, seed=7, draws=300)
    second = sensitivity_report(k=20, component=component, seed=7, draws=300)
    assert first.lower_lr == second.lower_lr
    assert first.upper_lr == second.upper_lr


def test_sensitivity_rejects_nonsense_parameters() -> None:
    component = _component()
    with pytest.raises(ValueError, match="draws"):
        sensitivity_report(k=20, component=component, draws=0)
    with pytest.raises(ValueError, match="confidence"):
        sensitivity_report(k=20, component=component, confidence=1.0)


# --------------------------------------------------------------------------- #
# The optional posterior
# --------------------------------------------------------------------------- #
def test_the_posterior_requires_a_prior_the_caller_supplies() -> None:
    ratio = _ratio()
    assert 0.0 < ratio.posterior_probability(0.05) < 1.0
    assert ratio.posterior_probability(0.5) > ratio.posterior_probability(0.05)


@pytest.mark.parametrize("prior", [0.0, 1.0, -0.1, 1.5])
def test_an_unusable_prior_is_rejected(prior: float) -> None:
    """A prior of exactly 0 or 1 cannot be moved by any evidence."""
    with pytest.raises(ValueError, match="strictly between"):
        _ratio().posterior_probability(prior)


def test_prior_log_odds_must_be_finite() -> None:
    with pytest.raises(ValueError, match="finite"):
        _ratio().with_prior_log_odds(math.inf)


def test_the_posterior_is_the_prior_updated_by_the_ratio() -> None:
    """The library's only Bayesian arithmetic: one addition in log-odds space."""
    ratio = _ratio()
    prior = 0.25
    expected = 1 / (1 + math.exp(-(math.log(prior / (1 - prior)) + math.log(ratio.lr))))
    assert ratio.posterior_probability(prior) == pytest.approx(expected)


# --------------------------------------------------------------------------- #
# Claim elements
# --------------------------------------------------------------------------- #
def _asset() -> AssetRef:
    return AssetRef.native(Chain.BITCOIN, symbol="BTC", decimals=8)


def test_an_amount_band_contains_within_tolerance() -> None:
    band = AmountBand(nominal=100_000_000, tolerance=1_000_000, asset=_asset())
    assert band.contains(100_500_000)
    assert band.contains(99_500_000)
    assert not band.contains(102_000_000)


def test_an_exact_band_admits_only_its_nominal() -> None:
    band = AmountBand(nominal=100, asset=_asset())
    assert band.contains(100)
    assert not band.contains(101)


def test_tolerance_is_reported_relative_to_the_nominal() -> None:
    assert AmountBand(nominal=100, tolerance=5, asset=_asset()).relative_tolerance == 0.05
    # A tolerance around zero is proportionally unbounded and should look it.
    assert AmountBand(nominal=0, tolerance=5, asset=_asset()).relative_tolerance == math.inf


def test_a_band_scales_for_the_sensitivity_sweep() -> None:
    band = AmountBand(nominal=100, tolerance=10, asset=_asset())
    assert band.scaled(5).tolerance == 50


def test_a_window_states_its_edge_semantics() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 31, tzinfo=UTC)
    inclusive = ActivityWindow(start=start, end=end)
    exclusive = ActivityWindow(start=start, end=end, end_inclusive=False)
    assert inclusive.contains(start)
    assert inclusive.contains(end)
    assert exclusive.contains(start)
    assert not exclusive.contains(end)


def test_a_transaction_with_no_timestamp_is_outside_the_window() -> None:
    """Unknown is not the same as included, and counting it would inflate k."""
    window = ActivityWindow(
        start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 1, 31, tzinfo=UTC)
    )
    assert not window.contains(None)


def test_a_backwards_window_is_rejected() -> None:
    with pytest.raises(ValidationError, match="precedes its start"):
        ActivityWindow(start=datetime(2024, 2, 1, tzinfo=UTC), end=datetime(2024, 1, 1, tzinfo=UTC))


def test_a_claim_with_nothing_to_price_is_refused() -> None:
    """Its coincidence probability would be 1 and its ratio exactly 1 -- no evidence."""
    with pytest.raises(ValidationError, match="nothing to price"):
        ClaimElements(chain=Chain.BITCOIN, asset=_asset(), sender="bc1qsender")


def test_the_priced_elements_are_reported() -> None:
    both = ClaimElements(
        chain=Chain.BITCOIN,
        asset=_asset(),
        sender="bc1qa",
        recipient="bc1qb",
        band=AmountBand(nominal=100, asset=_asset()),
    )
    assert both.priced_elements == ("recipient", "amount")
    amount_only = ClaimElements(
        chain=Chain.BITCOIN,
        asset=_asset(),
        sender="bc1qa",
        band=AmountBand(nominal=100, asset=_asset()),
    )
    assert amount_only.priced_elements == ("amount",)
