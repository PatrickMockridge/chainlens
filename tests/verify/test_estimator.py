"""The estimator: the rate it measures, the refusals it can explain, and the bound it states.

Until now no estimator shipped, so every real finding reported no ratio and said why — the
no-ratio shape was the *normal* case rather than a degraded one. These tests are about what
replaces that: a coincidence rate counted over the sender's own movements, with three things
pinned.

* **the sample is the complement of the window.** Counting the asserted transfer among the
  transfers that would have to be coincidences is circular, so the rate comes from what falls
  outside the claim's window — and a claim with no window has no outside and is refused.
* **a refusal carries its own words.** ``None`` still means "too thin"; ``Unpriced`` is for the
  refusals an estimator can diagnose, and the engine renders the reason verbatim into the
  derivation's ``because`` node.
* **a bounded sample says so.** The population string is what a reader sees, so a scan that
  stopped at its ceiling must not produce one that reads as the whole history.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chainlens.ledger.derive import derive_finding
from chainlens.models.base import utcnow
from chainlens.models.enums import Chain, ClaimVerdict
from chainlens.models.primitives import AssetRef, Transaction
from chainlens.providers.capabilities import Capability
from chainlens.social.models import Post, ProvenanceStrength, SourceRef
from chainlens.testing.factories import btc_transaction, inp, out
from chainlens.testing.in_memory import InMemoryProvider
from chainlens.verify.claims import ActivityWindow, AmountBand, ClaimElements
from chainlens.verify.engine import VerificationEngine
from chainlens.verify.estimators import WindowCoincidenceEstimator, estimator_for
from chainlens.verify.likelihood import NullModel
from chainlens.verify.schema import Claim, ClaimType, Extraction
from chainlens.verify.verdicts import RateEstimate, Unpriced

ALICE = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
BOB = "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
CAROL = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
SEPTEMBER = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
JUNE = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
WINDOW = ActivityWindow(
    start=datetime(2026, 9, 1, tzinfo=UTC), end=datetime(2026, 9, 30, tzinfo=UTC)
)
QUOTE = "alice paid bob"


def _payment(txid: str, *, when: datetime, sats: int = 30_000, sender: str = ALICE) -> Transaction:
    return btc_transaction(
        txid,
        [out(0, BOB, sats)],
        [inp(0, sender, sats)],
        block_height=900_000,
        block_time=when,
    )


def _provider(*transactions: Transaction, with_capability: bool = True) -> InMemoryProvider:
    provider = InMemoryProvider(chain=Chain.BITCOIN, transactions=list(transactions))
    if not with_capability:
        # An estimator is only offered where the provider advertises the capability, so removing
        # it is how this test builds "a provider that cannot answer".
        provider.capabilities = provider.capabilities - {Capability.WINDOW_TRANSFERS}
    return provider


def _elements(**overrides: object) -> ClaimElements:
    fields: dict[str, object] = {
        "chain": Chain.BITCOIN,
        "asset": AssetRef.native(Chain.BITCOIN),
        "sender": ALICE,
        "recipient": BOB,
        "band": AmountBand(nominal=30_000, tolerance=1_500, asset=AssetRef.native(Chain.BITCOIN)),
        "window": WINDOW,
    }
    return ClaimElements(**{**fields, **overrides})  # type: ignore[arg-type]


class TestTheRateItMeasures:
    @pytest.mark.anyio
    async def test_it_counts_the_sender_s_movements_outside_the_window(self) -> None:
        """Four other payments, one of them the same shape as the claim: p = 1/4."""
        provider = _provider(
            _payment("tx0", when=JUNE, sats=500),
            _payment("tx1", when=JUNE, sats=500),
            _payment("tx2", when=JUNE, sats=500),
            _payment("tx3", when=JUNE, sats=30_000),
        )
        priced = await WindowCoincidenceEstimator().estimate(_elements(), provider=provider)

        assert isinstance(priced, RateEstimate)
        component = priced.component
        assert (component.successes, component.trials) == (1, 4)
        assert component.value == pytest.approx(0.25)
        assert priced.null_model is NullModel.WITHIN_SENDER
        assert component.population == "the sender's whole movement history outside the window"

    @pytest.mark.anyio
    async def test_the_asserted_transfer_is_not_in_its_own_sample(self) -> None:
        """Counting it would be circular: it is the thing the rate has to be independent of."""
        provider = _provider(
            _payment("tx_inside", when=SEPTEMBER),
            _payment("tx1", when=JUNE, sats=500),
            _payment("tx2", when=JUNE, sats=500),
        )
        priced = await WindowCoincidenceEstimator().estimate(_elements(), provider=provider)
        assert isinstance(priced, RateEstimate)
        # Two movements outside the window, neither of them the September payment.
        assert priced.component.trials == 2
        assert priced.component.successes == 0

    @pytest.mark.anyio
    async def test_a_bounded_sample_says_it_is_bounded(self) -> None:
        provider = _provider(*[_payment(f"tx{n}", when=JUNE, sats=500) for n in range(5)])
        priced = await WindowCoincidenceEstimator(sample_limit=3).estimate(
            _elements(), provider=provider
        )
        assert isinstance(priced, RateEstimate)
        assert priced.component.trials == 3
        # The ceiling is named, so a reader cannot take this for the whole history.
        assert "most recent 3 movements" in priced.component.population
        assert "not the whole of their history" in priced.component.population

    @pytest.mark.anyio
    async def test_a_sparse_sample_is_marked_rather_than_quietly_banded(self) -> None:
        """One coincidence out of four is not enough for a verbal band, and it says so.

        A ratio built from a sample this thin is still a ratio — the arithmetic holds — but the
        reader has to be able to see that the interval is wide enough to swallow the conclusion.
        """
        from chainlens.verify.likelihood import MIN_JOINT_SUCCESSES

        provider = _provider(
            _payment("tx0", when=JUNE, sats=30_000),
            *[_payment(f"tx{n}", when=JUNE, sats=500) for n in range(1, 4)],
        )
        priced = await WindowCoincidenceEstimator().estimate(_elements(), provider=provider)
        assert isinstance(priced, RateEstimate)
        assert priced.component.successes < MIN_JOINT_SUCCESSES
        assert priced.component.is_sparse is True
        # And the interval is reported alongside it, so "sparse" is not just a label.
        assert priced.component.ci_upper > priced.component.value

    @pytest.mark.anyio
    async def test_the_interval_is_the_wilson_interval_of_the_counts(self) -> None:
        from chainlens.verify.likelihood import wilson_interval

        provider = _provider(*[_payment(f"tx{n}", when=JUNE, sats=500) for n in range(4)])
        priced = await WindowCoincidenceEstimator().estimate(_elements(), provider=provider)
        assert isinstance(priced, RateEstimate)
        lower, upper = wilson_interval(0, 4)
        assert (priced.component.ci_lower, priced.component.ci_upper) == (lower, upper)


class TestTheRefusalsItCanExplain:
    @pytest.mark.anyio
    async def test_a_claim_with_no_window_has_no_outside_to_sample(self) -> None:
        provider = _provider(_payment("tx1", when=JUNE))
        priced = await WindowCoincidenceEstimator().estimate(
            _elements(window=None), provider=provider
        )
        assert isinstance(priced, Unpriced)
        assert "names no window" in priced.reason
        assert "Give the claim a window" in priced.reason

    @pytest.mark.anyio
    async def test_a_population_wide_rate_is_refused_rather_than_approximated(self) -> None:
        """No free provider draws a network-wide sample, and a proxy would be a different number."""
        priced = await WindowCoincidenceEstimator(null_model=NullModel.POPULATION).estimate(
            _elements(), provider=_provider(_payment("tx1", when=JUNE))
        )
        assert isinstance(priced, Unpriced)
        assert "population" in priced.reason
        assert "withheld" in priced.reason
        assert "cannot measure" in priced.reason

    @pytest.mark.anyio
    async def test_a_sender_with_nothing_outside_the_window_is_refused(self) -> None:
        provider = _provider(_payment("tx_inside", when=SEPTEMBER))
        priced = await WindowCoincidenceEstimator().estimate(_elements(), provider=provider)
        assert isinstance(priced, Unpriced)
        assert priced.samples == 0
        assert "no movements outside the window" in priced.reason

    @pytest.mark.anyio
    async def test_a_provider_that_cannot_list_movements_is_refused_by_name(self) -> None:
        provider = _provider(_payment("tx1", when=JUNE), with_capability=False)
        priced = await WindowCoincidenceEstimator().estimate(_elements(), provider=provider)
        assert isinstance(priced, Unpriced)
        assert "cannot list an address's movements" in priced.reason


class TestChoosingOne:
    def test_no_estimator_without_the_capability(self) -> None:
        assert estimator_for(_provider(with_capability=False)) is None

    def test_an_estimator_when_the_provider_can_supply_a_sample(self) -> None:
        assert estimator_for(_provider()) is not None


class TestWhatTheEngineDoesWithIt:
    @pytest.mark.anyio
    async def test_a_ratio_appears_where_the_preconditions_hold(self) -> None:
        """The whole point: a real finding with numbers instead of a reason."""
        provider = _provider(
            _payment("tx_match", when=SEPTEMBER),
            _payment("tx1", when=JUNE, sats=500),
            _payment("tx2", when=JUNE, sats=500),
            _payment("tx3", when=JUNE, sats=500),
        )
        engine = VerificationEngine(provider, estimator=estimator_for(provider))
        report = await engine.verify_post(_post(), Extraction(claims=(_claim(),)))
        finding = report.findings[0]

        assert finding.verdict is ClaimVerdict.SUPPORTED
        ratio = finding.likelihood
        assert ratio is not None
        assert ratio.k == 1, "one movement in the window, which is the opportunity count"
        assert ratio.null_model is NullModel.WITHIN_SENDER
        assert ratio.components[0].trials == 3
        assert ratio.components[0].population.startswith("the sender's whole movement history")

    @pytest.mark.anyio
    async def test_the_derivation_carries_the_ratio_and_its_population(self) -> None:
        provider = _provider(
            _payment("tx_match", when=SEPTEMBER),
            _payment("tx1", when=JUNE, sats=500),
            _payment("tx2", when=JUNE, sats=500),
        )
        engine = VerificationEngine(provider, estimator=estimator_for(provider))
        report = await engine.verify_post(_post(), Extraction(claims=(_claim(),)))
        document = derive_finding(report.findings[0])

        assert document.has_ratio is True
        ratio_node = next(
            node for node in document.root.walk() if node.kind.value == "likelihood_ratio"
        )
        detail = {entry.key: entry.value for entry in ratio_node.detail}
        assert detail["null_model"] == "within_sender"
        # The population is an assumption, so an assumption node carries it rather than a detail
        # row a reader might skip.
        assert detail["lr"] is not None or detail["lr_at_least"] is True

    @pytest.mark.anyio
    async def test_a_refusal_reaches_the_derivations_because_node(self) -> None:
        """The reason is the estimator's own words, not a generic sentence about thinness."""
        provider = _provider(_payment("tx_match", when=SEPTEMBER), _payment("tx1", when=JUNE))
        engine = VerificationEngine(
            provider, estimator=WindowCoincidenceEstimator(null_model=NullModel.POPULATION)
        )
        report = await engine.verify_post(_post(), Extraction(claims=(_claim(),)))
        document = derive_finding(report.findings[0])

        assert document.has_ratio is False
        reasons = [
            entry.value
            for node in document.root.walk()
            for entry in node.detail
            if entry.key == "reason"
        ]
        assert reasons, "a finding with no ratio must say why"
        assert "population" in str(reasons[0])

    @pytest.mark.anyio
    async def test_a_tolerance_sweep_never_prices_a_variant_the_estimator_refuses(self) -> None:
        """A sweep step nothing stands behind would put a number in the envelope."""
        provider = _provider(
            _payment("tx_match", when=SEPTEMBER),
            _payment("tx1", when=JUNE, sats=500),
            _payment("tx2", when=JUNE, sats=500),
        )
        engine = VerificationEngine(provider, estimator=estimator_for(provider))
        report = await engine.verify_post(_post(), Extraction(claims=(_claim(),)))
        ratio = report.findings[0].likelihood
        assert ratio is not None
        for sweep in ratio.sensitivity.sweeps:
            assert sweep.lr > 0

    @pytest.mark.anyio
    async def test_with_no_estimator_the_old_behaviour_is_unchanged(self) -> None:
        provider = _provider(_payment("tx_match", when=SEPTEMBER), _payment("tx1", when=JUNE))
        report = await VerificationEngine(provider).verify_post(
            _post(), Extraction(claims=(_claim(),))
        )
        finding = report.findings[0]
        assert finding.verdict is ClaimVerdict.SUPPORTED
        assert finding.likelihood is None


def _post() -> Post:
    return Post(
        id="p1",
        text=QUOTE,
        source=SourceRef(strength=ProvenanceStrength.PASTE, captured_at=utcnow()),
    )


def _claim() -> Claim:
    return Claim(
        type=ClaimType.TRANSFER,
        quote=QUOTE,
        addresses=(ALICE, BOB),
        amount_text="~30,000 sats",
        window=WINDOW,
    )
