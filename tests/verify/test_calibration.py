"""The Cllr harness: the metric's arithmetic, its preconditions, and what a report keeps apart.

The numbers here are hand-computed from the definition, not read off the implementation:

    Cllr = 1/(2·N_same) · Σ_same log₂(1 + 1/LR) + 1/(2·N_diff) · Σ_diff log₂(1 + LR)

Two of them are worth walking through. A set that separates the classes perfectly but scores
every different-source case at ``LR = 1`` — the best this library can do, since a ratio may not
fall below 1 — costs ``0.5``: half a bit per non-target, times its weight. And a set where a
target scores *below* a non-target has no ranking information at all, so its ``Cllr_min`` is
``1``: the pool-adjacent-violators merge that makes the two trials one block is the metric saying
that no monotone re-mapping can rescue an inverted pair.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from chainlens.models.base import utcnow
from chainlens.models.enums import Chain, ClaimVerdict
from chainlens.providers.capabilities import Capability
from chainlens.social.models import Post, ProvenanceStrength, SourceRef
from chainlens.testing.factories import btc_transaction, inp, out
from chainlens.testing.in_memory import InMemoryProvider
from chainlens.verify.calibration import (
    CalibrationCase,
    CalibrationTrial,
    GroundTruth,
    case_from_finding,
    log_likelihood_ratio_cost,
    report_from_cases,
)
from chainlens.verify.claims import ActivityWindow
from chainlens.verify.engine import VerificationEngine
from chainlens.verify.estimators import estimator_for
from chainlens.verify.schema import Claim, ClaimType, Extraction
from chainlens.verify.verdicts import VerificationFinding

ALICE = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
BOB = "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
SEPTEMBER = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
JUNE = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def _trial(log10_lr: float, *, same: bool) -> CalibrationTrial:
    return CalibrationTrial(score=log10_lr, same_source=same)


class TestTheArithmetic:
    def test_a_perfect_ranking_at_the_library_s_floor_costs_half_a_bit(self) -> None:
        """``LR = 1`` is the best a different-source case can be scored, and it costs half a bit."""
        cost = log_likelihood_ratio_cost(
            [
                _trial(2.0, same=True),
                _trial(2.0, same=True),
                _trial(0.0, same=False),
                _trial(0.0, same=False),
            ]
        )
        # Two targets at LR=100 contribute 2 · (1/4) · log₂(1.01); the non-targets contribute
        # 2 · (1/4) · log₂(2), which is exactly the half-bit floor.
        assert cost.cllr == pytest.approx(0.5 + 0.5 * math.log2(1.01))
        assert cost.cllr_min == pytest.approx(0.0)
        assert cost.calibration_loss == pytest.approx(cost.cllr - cost.cllr_min)
        assert (cost.same_source, cost.different_source) == (2, 2)

    def test_an_inverted_pair_cannot_be_rescued_by_a_recalibration(self) -> None:
        """A target below a non-target is the one thing a monotone map cannot fix."""
        cost = log_likelihood_ratio_cost([_trial(0.0, same=True), _trial(1.0, same=False)])
        # cllr: (1/2)·log₂(2) + (1/2)·log₂(11) = 0.5 + 1.7297
        assert cost.cllr == pytest.approx(0.5 + 0.5 * math.log2(11))
        # The violator merge puts both trials in one block at p = 1/2, which costs a full bit —
        # the whole of the information the pair had, which is none.
        assert cost.cllr_min == pytest.approx(1.0)
        assert cost.calibration_loss == pytest.approx(0.5 * math.log2(11) - 0.5)

    def test_no_information_anywhere_costs_exactly_one_bit(self) -> None:
        """Every ratio 1: the metric's own definition of an uninformative answer.

        This is also the test that caught a bug in the first implementation. Three trials sharing
        one score were treated as three *ordered* bands, so the pool-adjacent-violators pass found
        a merge that lowered the cost below the true minimum — crediting a recalibration with
        separating scores it cannot separate, since a monotone map must give equal scores equal
        values. Trials are grouped by score before the merges now, and the unbalanced corpus here
        is what makes the difference visible: a balanced one has the same cost either way.
        """
        cost = log_likelihood_ratio_cost(
            [_trial(0.0, same=True), _trial(0.0, same=False), _trial(0.0, same=True)]
        )
        assert cost.cllr == pytest.approx(1.0)
        assert cost.cllr_min == pytest.approx(1.0)
        assert cost.calibration_loss == pytest.approx(0.0)

    def test_the_cost_never_falls_below_the_floor_the_library_imposes(self) -> None:
        """A reported ratio is at least 1, so every non-target costs at least half a bit."""
        for same_scores in ([0.0], [1.0, 2.0], [0.1, 0.2, 0.3]):
            for diff_scores in ([0.0], [0.0, 3.0], []):
                if not diff_scores:
                    continue
                trials = [_trial(s, same=True) for s in same_scores] + [
                    _trial(s, same=False) for s in diff_scores
                ]
                assert log_likelihood_ratio_cost(trials).cllr >= 0.5

    def test_a_recalibration_can_never_do_worse_than_nothing(self) -> None:
        """The identity is a monotone map, so ``Cllr_min`` cannot exceed ``Cllr``."""
        for scores in ([2.0, 1.5, 0.5, 0.0], [3.0, 0.0, 1.0, 2.0, 0.5], [1.0, 1.0, 1.0, 0.0]):
            trials = [_trial(score, same=index % 2 == 0) for index, score in enumerate(scores)]
            cost = log_likelihood_ratio_cost(trials)
            assert cost.cllr_min <= cost.cllr + 1e-12
            assert cost.calibration_loss >= -1e-12

    def test_one_class_is_refused_rather_than_reported(self) -> None:
        """With one class every set of ratios costs the same, so the number would mean nothing."""
        with pytest.raises(ValueError, match="needs both classes"):
            log_likelihood_ratio_cost([_trial(1.0, same=True), _trial(2.0, same=True)])
        with pytest.raises(ValueError, match="needs both classes"):
            log_likelihood_ratio_cost([_trial(1.0, same=False)])

    def test_an_unbounded_ratio_is_free_when_right_and_infinite_when_wrong(self) -> None:
        """The metric agreeing with the library's own rule about infinities."""
        right = log_likelihood_ratio_cost([_trial(math.inf, same=True), _trial(0.0, same=False)])
        # The target contributes log₂(1 + 0) = 0; only the non-target's half bit remains.
        assert right.cllr == pytest.approx(0.5)

        wrong = log_likelihood_ratio_cost([_trial(0.0, same=True), _trial(math.inf, same=False)])
        assert wrong.cllr == math.inf
        # The recalibration still has something to work with, which is the useful part of the
        # report: the ratios rank badly *and* are on the wrong scale.
        assert math.isfinite(wrong.cllr_min)


class TestReadingAFinding:
    def _finding(self, *, verdict: ClaimVerdict, reason: str | None = None) -> VerificationFinding:
        return VerificationFinding(
            post_id="p1",
            provenance_strength=ProvenanceStrength.PASTE,
            claim=Claim(type=ClaimType.TRANSFER, quote="q"),
            verdict=verdict,
            method="transfer",
            reason=reason,
        )

    def test_a_contradiction_is_not_a_refusal(self) -> None:
        """A ratio is never below 1, so a contradicted claim could not have carried one anyway."""
        case = case_from_finding(
            "c1", GroundTruth.DIFFERENT_SOURCE, self._finding(verdict=ClaimVerdict.CONTRADICTED)
        )
        assert case.priced is False
        assert case.refusal is None

    def test_a_supported_finding_without_a_ratio_is_a_refusal_with_its_reason(self) -> None:
        case = case_from_finding(
            "c2",
            GroundTruth.SAME_SOURCE,
            self._finding(verdict=ClaimVerdict.SUPPORTED, reason="the claim names no window"),
        )
        assert case.priced is True
        assert case.score is None
        assert case.refusal == "the claim names no window"

    def test_a_finding_with_a_ratio_carries_its_logarithm_as_the_score(self) -> None:
        from chainlens.verify.likelihood import (
            ComponentEstimate,
            EstimatorMethod,
            NullModel,
            evaluate_likelihood,
            wilson_interval,
        )

        lower, upper = wilson_interval(1, 100)
        finding = self._finding(verdict=ClaimVerdict.SUPPORTED)
        finding = finding.model_copy(
            update={
                "likelihood": evaluate_likelihood(
                    k=10,
                    component=ComponentEstimate(
                        value=0.01,
                        successes=1,
                        trials=100,
                        ci_lower=lower,
                        ci_upper=upper,
                        method=EstimatorMethod.EMPIRICAL_JOINT,
                        population="the sender's own transfers",
                    ),
                    null_model=NullModel.WITHIN_SENDER,
                )
            }
        )
        case = case_from_finding("c3", GroundTruth.SAME_SOURCE, finding)
        assert case.priced is True
        assert case.score == pytest.approx(finding.likelihood.log10_lr)  # type: ignore[union-attr]


class TestWhatAReportKeepsApart:
    def test_coverage_is_over_priceable_cases_only(self) -> None:
        """A contradicted claim is not a missing ratio, and counting it as one would blame the
        estimator for arithmetic."""
        report = report_from_cases(
            [
                CalibrationCase("a", GroundTruth.SAME_SOURCE, score=1.0),
                CalibrationCase("b", GroundTruth.DIFFERENT_SOURCE, refusal="no window"),
                CalibrationCase("c", GroundTruth.SAME_SOURCE, priced=False),
                CalibrationCase("d", GroundTruth.DIFFERENT_SOURCE, priced=False),
            ]
        )
        assert (report.cases, report.priced, report.refused, report.not_applicable) == (4, 1, 1, 2)
        assert report.coverage == pytest.approx(0.5)

    def test_the_refusal_reasons_are_counted_rather_than_summarised(self) -> None:
        report = report_from_cases(
            [
                CalibrationCase("a", GroundTruth.SAME_SOURCE, refusal="the claim names no window"),
                CalibrationCase("b", GroundTruth.SAME_SOURCE, refusal="the claim names no window"),
                CalibrationCase("c", GroundTruth.DIFFERENT_SOURCE, refusal="no movements outside"),
            ]
        )
        assert report.refusals == {
            "the claim names no window": 2,
            "no movements outside": 1,
        }
        assert "refused x2: the claim names no window" in report.format()

    def test_a_single_class_corpus_reports_no_cost_and_says_why(self) -> None:
        report = report_from_cases(
            [
                CalibrationCase("a", GroundTruth.SAME_SOURCE, score=2.0),
                CalibrationCase("b", GroundTruth.SAME_SOURCE, score=1.0),
            ]
        )
        assert report.cost is None
        assert any("needs both classes" in warning for warning in report.warnings)
        assert "no Cllr" in report.format()

    def test_an_unbounded_trial_is_warned_about(self) -> None:
        report = report_from_cases(
            [
                CalibrationCase("a", GroundTruth.SAME_SOURCE, score=math.inf),
                CalibrationCase("b", GroundTruth.DIFFERENT_SOURCE, score=0.0),
            ]
        )
        assert report.cost is not None
        assert any("unbounded" in warning for warning in report.warnings)


class TestTheHarnessEndToEnd:
    """Over a corpus whose truth the generator sets, which is what a synthetic corpus can do.

    The engine cannot see the labels — the two classes here are mechanically identical, and the
    difference is which one the *generator* made up — and that is the honest shape of the thing: a
    harness measures ratios against truth it is given, and this corpus's truth measures plumbing
    rather than accuracy. See the module docstring.
    """

    def _provider(self) -> InMemoryProvider:
        # One payment inside the window, and four outside it — one of which looks like the claim,
        # so the coincidence rate is 1/4 and the ratio is finite.
        return InMemoryProvider(
            chain=Chain.BITCOIN,
            transactions=[
                btc_transaction(
                    "tx_match",
                    [out(0, BOB, 30_000)],
                    [inp(0, ALICE, 30_000)],
                    block_height=900_000,
                    block_time=SEPTEMBER,
                ),
                btc_transaction(
                    "tx_lookalike",
                    [out(0, BOB, 30_000)],
                    [inp(0, ALICE, 30_000)],
                    block_height=800_000,
                    block_time=JUNE,
                ),
                *[
                    btc_transaction(
                        f"tx_other{n}",
                        [out(0, BOB, 500)],
                        [inp(0, ALICE, 500)],
                        block_height=800_000 + n,
                        block_time=JUNE,
                    )
                    for n in range(3)
                ],
            ],
        )

    def _claim(self) -> Claim:
        return Claim(
            type=ClaimType.TRANSFER,
            quote="alice paid bob",
            addresses=(ALICE, BOB),
            amount_text="~30,000 sats",
            window=ActivityWindow(
                start=datetime(2026, 9, 1, tzinfo=UTC), end=datetime(2026, 9, 30, tzinfo=UTC)
            ),
        )

    async def _finding(self, provider: InMemoryProvider) -> VerificationFinding:
        post = Post(
            id="p1",
            text="alice paid bob",
            source=SourceRef(strength=ProvenanceStrength.PASTE, captured_at=utcnow()),
        )
        engine = VerificationEngine(provider, estimator=estimator_for(provider))
        report = await engine.verify_post(post, Extraction(claims=(self._claim(),)))
        return report.findings[0]

    @pytest.mark.anyio
    async def test_a_priced_corpus_produces_a_finite_cost(self) -> None:
        finding = await self._finding(self._provider())
        assert finding.likelihood is not None
        assert Capability.WINDOW_TRANSFERS in self._provider().capabilities

        cases = [
            case_from_finding("same", GroundTruth.SAME_SOURCE, finding),
            case_from_finding("different", GroundTruth.DIFFERENT_SOURCE, finding),
        ]
        report = report_from_cases(cases)

        assert (report.cases, report.priced, report.refused, report.not_applicable) == (2, 2, 0, 0)
        assert report.coverage == pytest.approx(1.0)
        assert report.cost is not None
        assert math.isfinite(report.cost.cllr)
        assert report.cost.cllr >= 0.5, "the floor a ratio of at least 1 imposes"
        assert report.cost.calibration_loss >= 0

    @pytest.mark.anyio
    async def test_a_corpus_of_refusals_reports_no_cost_and_the_reasons(self) -> None:
        """Coverage is the honest headline when the estimator could not price anything."""
        finding = await self._finding(self._provider())
        refused = case_from_finding(
            "refused",
            GroundTruth.SAME_SOURCE,
            finding.model_copy(update={"likelihood": None, "reason": "the claim names no window"}),
        )
        report = report_from_cases([refused])

        assert (report.priced, report.refused) == (0, 1)
        assert report.coverage == pytest.approx(0.0)
        assert report.cost is None
        assert report.refusals == {"the claim names no window": 1}
        assert "coverage: 0%" in report.format()
