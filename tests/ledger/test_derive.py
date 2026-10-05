"""Tests for the derivation: both shapes, and the choices that protect against misreading.

The two shapes are tested separately and deliberately, because the no-ratio one is the
*normal* case today — no coincidence estimator ships, so most findings have no ratio — and a
derivation view that only looked right with a ratio would look broken in every demo.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chainlens.ledger.derive import PRIOR_LIMITATIONS, claim_id, derive_finding
from chainlens.models.base import utcnow
from chainlens.models.derive import DerivationDocument, DerivationKind, DerivationNode
from chainlens.models.enums import Chain, ClaimVerdict, VerbalScale
from chainlens.models.wire import GraphRefKind
from chainlens.providers.base import Provider
from chainlens.social.models import Post, ProvenanceStrength, SourceRef
from chainlens.testing.factories import btc_transaction, inp, out
from chainlens.testing.in_memory import InMemoryProvider
from chainlens.verify.claims import ClaimElements
from chainlens.verify.engine import VerificationEngine
from chainlens.verify.likelihood import (
    ComponentEstimate,
    EstimatorMethod,
    NullModel,
    wilson_interval,
)
from chainlens.verify.schema import Claim, ClaimType, Extraction
from chainlens.verify.verdicts import RateEstimate, VerificationFinding

ALICE = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
BOB = "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
WHEN = datetime(2026, 9, 10, tzinfo=UTC)


class _Pricing:
    """An estimator that prices a band by its width, so the sweep is observable.

    A stub that returned the same value for every variant would make the tolerance sweep
    untestable: the sweep's whole point is that widening the band raises ``p``.
    """

    def __init__(self, base: float = 1e-4) -> None:
        self.base = base
        self.calls = 0

    async def estimate(self, elements: ClaimElements, *, provider: Provider) -> RateEstimate | None:
        self.calls += 1
        band = elements.band
        wider = 1 + (band.tolerance / band.nominal if band and band.nominal else 0)
        # A zero rate needs zero successes to carry a coherent interval; three of thirty
        # thousand cannot have a lower bound of zero, and the model rightly refuses it.
        successes = 0 if self.base == 0 else 3
        lower, upper = wilson_interval(successes, 30_000)
        return RateEstimate(
            component=ComponentEstimate(
                value=self.base * wider,
                successes=successes,
                trials=30_000,
                ci_lower=lower,
                ci_upper=upper,
                method=EstimatorMethod.EMPIRICAL_JOINT,
                population="the sender's own out-of-window transfers",
            ),
            null_model=NullModel.WITHIN_SENDER,
        )


def _provider(*, transactions: int = 3) -> InMemoryProvider:
    return InMemoryProvider(
        chain=Chain.BITCOIN,
        transactions=[
            btc_transaction(
                f"tx{index}",
                [out(0, BOB, 4_000_000_000_000)],
                [inp(0, ALICE, 4_000_000_000_000 + index)],
                block_height=index,
                block_time=WHEN,
            )
            for index in range(1, transactions + 1)
        ],
    )


def _post() -> Post:
    return Post(
        id="post-1",
        text="the post",
        source=SourceRef(strength=ProvenanceStrength.PRINTOUT, captured_at=utcnow()),
    )


def _claim(amount_text: str = "~40k BTC") -> Claim:
    return Claim(
        type=ClaimType.TRANSFER, quote="the post", addresses=(ALICE, BOB), amount_text=amount_text
    )


async def _finding(
    *,
    estimator: object | None = None,
    transactions: int = 3,
    amount_text: str = "~40k BTC",
) -> VerificationFinding:
    engine = VerificationEngine(_provider(transactions=transactions), estimator=estimator)  # type: ignore[arg-type]
    report = await engine.verify_post(_post(), Extraction(claims=(_claim(amount_text),)))
    return report.findings[0]


def _kinds(document: DerivationDocument) -> dict[DerivationKind, list[DerivationNode]]:
    found: dict[DerivationKind, list[DerivationNode]] = {}
    for node in document.root.walk():
        found.setdefault(node.kind, []).append(node)
    return found


# --------------------------------------------------------------------------- #
# The shape without a ratio — the normal case today
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_the_no_ratio_tree_is_short_rather_than_full_of_holes() -> None:
    """No hypothesised pair is drawn, because with no ratio there are none.

    Drawing first/alternative above an empty ratio node is exactly the shape that looks
    broken, and while no estimator ships it would be the shape of almost every finding.
    """
    finding = await _finding()
    assert finding.likelihood is None

    document = derive_finding(finding)
    kinds = set(_kinds(document))

    assert DerivationKind.BECAUSE in kinds
    assert DerivationKind.VERDICT in kinds
    assert DerivationKind.PROPOSITION not in kinds
    assert DerivationKind.LIKELIHOOD_RATIO not in kinds
    assert not document.has_ratio


@pytest.mark.anyio
async def test_the_refusal_reason_is_reproduced_verbatim() -> None:
    """The engine's own wording, not a paraphrase of it.

    The six refusal reasons are specific — "the scan was not exhaustive" and "no coincidence
    estimator is configured" mean different things and have different remedies — so a
    summary would lose the distinction, and substituting one would be the library's words
    standing in for its own.
    """
    finding = await _finding()
    assert finding.reason

    document = derive_finding(finding)
    because = _kinds(document)[DerivationKind.BECAUSE][0]
    assert because.label == finding.reason
    assert {entry.key: entry.value for entry in because.detail}["reason"] == finding.reason


@pytest.mark.anyio
async def test_the_verdict_holds_the_evidence_and_the_reason() -> None:
    document = derive_finding(await _finding())
    verdict = _kinds(document)[DerivationKind.VERDICT][0]
    child_kinds = {child.kind for child in verdict.children}
    assert child_kinds == {DerivationKind.EVIDENCE, DerivationKind.BECAUSE}


@pytest.mark.anyio
async def test_an_unverifiable_finding_without_a_reason_refuses_to_render() -> None:
    """A reader must not be able to read it as an accusation.

    The same rule the case-study guardrails enforce on the text: ``UNVERIFIABLE`` means no
    method here addresses this class of claim, and a derivation that rendered it bare would
    present a blank where an explanation has to be.
    """
    finding = VerificationFinding(
        post_id="p",
        provenance_strength=ProvenanceStrength.PASTE,
        claim=_claim(),
        verdict=ClaimVerdict.UNVERIFIABLE,
        method="none",
        reason=None,
    )
    with pytest.raises(ValueError, match="must carry the engine's own meaning"):
        derive_finding(finding)


@pytest.mark.anyio
async def test_an_unverifiable_finding_with_a_reason_renders() -> None:
    finding = VerificationFinding(
        post_id="p",
        provenance_strength=ProvenanceStrength.PASTE,
        claim=_claim(),
        verdict=ClaimVerdict.UNVERIFIABLE,
        method="label",
        reason="no label source is configured, so no method exists for this claim",
    )
    document = derive_finding(finding)
    assert document.verdict is ClaimVerdict.UNVERIFIABLE
    assert not document.is_informative


# --------------------------------------------------------------------------- #
# The shape with a ratio
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_the_ratio_tree_carries_both_hypotheses() -> None:
    finding = await _finding(estimator=_Pricing())
    assert finding.likelihood is not None

    document = derive_finding(finding)
    propositions = _kinds(document)[DerivationKind.PROPOSITION]

    assert len(propositions) == 3, "a parent proposition node and its two arms"
    summaries = [node.summary for node in propositions]
    assert any("the specific payment" in (text or "") for text in summaries)
    assert any("coincidentally looks like" in (text or "") for text in summaries)


@pytest.mark.anyio
async def test_the_alternative_hypothesis_is_written_from_the_null_model() -> None:
    """Its text is canned, not generated, and chosen by the enum.

    ``within_sender`` and ``population`` describe genuinely different coincidence mechanisms,
    and which one was priced changes what the ratio means.
    """
    finding = await _finding(estimator=_Pricing())
    document = derive_finding(finding)
    alternative = [
        node
        for node in _kinds(document)[DerivationKind.PROPOSITION]
        if (node.summary or "").startswith("one of the sender's own")
    ]
    assert alternative, "a within-sender null model must say so in those terms"
    detail = {entry.key: entry.value for entry in alternative[0].detail}
    assert detail["null_model"] == NullModel.WITHIN_SENDER.value


@pytest.mark.anyio
async def test_both_measured_quantities_are_steps_of_their_own() -> None:
    """k and p are separate from the evidence, because a measurement is a different claim.

    The evidence says what was observed; ``k`` and ``p`` say what was counted and estimated.
    Collapsing them into one node would hide which number a reader is disagreeing with.
    """
    finding = await _finding(estimator=_Pricing())
    ratio = finding.likelihood
    assert ratio is not None

    kinds = _kinds(derive_finding(finding))
    k_node = kinds[DerivationKind.QUANTITY_K][0]
    p_node = kinds[DerivationKind.QUANTITY_P][0]
    assert k_node.value == float(finding.evidence.candidates_considered or 0)
    assert p_node.value == ratio.p


@pytest.mark.anyio
async def test_p_carries_the_sample_it_was_estimated_from() -> None:
    """A rate from 3 observations and one from 30,000 look identical without this."""
    finding = await _finding(estimator=_Pricing())
    document = derive_finding(finding)
    detail = {
        entry.key: entry.value for entry in _kinds(document)[DerivationKind.QUANTITY_P][0].detail
    }
    assert detail["successes"] == 3
    assert detail["trials"] == 30_000
    assert detail["method"] == EstimatorMethod.EMPIRICAL_JOINT.value
    assert "is_sparse" in detail


@pytest.mark.anyio
async def test_the_envelope_sits_between_the_ratio_and_the_band() -> None:
    """The one structural choice that resists the obvious misreading.

    A left-to-right flow culminating in a ratio presents it as the natural endpoint of the
    evidence. Putting the fragility between the ratio and the band means a reader meets the
    envelope before the conclusion it qualifies, rather than beside it.
    """
    finding = await _finding(estimator=_Pricing())
    document = derive_finding(finding)

    ratio = _kinds(document)[DerivationKind.LIKELIHOOD_RATIO][0]
    assert [child.kind for child in ratio.children] == [DerivationKind.SENSITIVITY]

    envelope = ratio.children[0]
    bands = [child for child in envelope.children if child.kind is DerivationKind.VERBAL_BAND]
    assert len(bands) == 1, "the band is a child of the envelope, not a sibling of the ratio"


@pytest.mark.anyio
async def test_the_band_shown_is_the_headline_band_from_the_library() -> None:
    """Computed in Python, so a renderer cannot drift from the conservative rule."""
    finding = await _finding(estimator=_Pricing())
    ratio = finding.likelihood
    assert ratio is not None

    document = derive_finding(finding)
    envelope = _kinds(document)[DerivationKind.SENSITIVITY][0]
    band = next(child for child in envelope.children if child.kind is DerivationKind.VERBAL_BAND)
    assert band.band is ratio.sensitivity.headline_band


@pytest.mark.anyio
async def test_every_sweep_is_a_branch() -> None:
    """A fragility claim is only checkable if the branches that produced it are shown."""
    finding = await _finding(estimator=_Pricing())
    document = derive_finding(finding)
    envelope = _kinds(document)[DerivationKind.SENSITIVITY][0]
    sweeps = [child for child in envelope.children if child.kind is DerivationKind.SENSITIVITY]
    assert finding.likelihood is not None
    assert len(sweeps) == len(finding.likelihood.sensitivity.sweeps)
    assert all(sweep.band is not None for sweep in sweeps)


@pytest.mark.anyio
async def test_the_tolerance_sweep_actually_varies() -> None:
    """Regression, and the reason this was invisible.

    ``sensitivity_report``'s variants are alternative *probabilities*. The engine passed a
    tolerance in base units, which crashed ``coincidence_probability``'s range check — but
    only for a claim that had a tolerance. The single engine test that reached the ratio used
    an exactly-stated amount, whose variants were all zero: a sweep that varied nothing, and
    passed.
    """
    finding = await _finding(estimator=_Pricing(), amount_text="~40k BTC")
    assert finding.likelihood is not None
    sweep_lrs = {sweep.lr for sweep in finding.likelihood.sensitivity.sweeps}
    assert len(sweep_lrs) > 1, "a sweep whose variants are all identical measures nothing"

    values = [
        sweep.lr for sweep in finding.likelihood.sensitivity.sweeps if sweep.name.startswith("p:")
    ]
    looser = next(
        sweep.lr for sweep in finding.likelihood.sensitivity.sweeps if sweep.name == "p:much looser"
    )
    assert looser == min(values), "a wider band must raise coincidence and so lower the ratio"


@pytest.mark.anyio
async def test_an_exactly_stated_amount_has_no_tolerance_to_sweep() -> None:
    """The converse, so the fix is not simply always-on."""
    finding = await _finding(estimator=_Pricing(), amount_text="40,000 BTC")
    assert finding.likelihood is not None
    assert all(sweep.name.startswith("k:") for sweep in finding.likelihood.sensitivity.sweeps), (
        "with no tolerance stated there is nothing to vary but k"
    )


# --------------------------------------------------------------------------- #
# The prior, which the library never supplies
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_no_posterior_without_a_prior() -> None:
    """The library ships no prior, so a posterior would rest on a base rate it invented."""
    finding = await _finding(estimator=_Pricing())
    document = derive_finding(finding)

    assert DerivationKind.POSTERIOR not in _kinds(document)
    assert document.limitations != PRIOR_LIMITATIONS
    assert document.prior_supplied_by is None


@pytest.mark.anyio
async def test_a_supplied_prior_produces_a_posterior_and_names_who_chose_it() -> None:
    finding = await _finding(estimator=_Pricing())
    document = derive_finding(finding, prior=1 / 1000, prior_supplied_by="the analyst")

    posterior = _kinds(document)[DerivationKind.POSTERIOR][0]
    assert document.prior_supplied_by == "the analyst"
    detail = {entry.key: entry.value for entry in posterior.detail}
    assert detail["supplied_by"] == "the analyst"
    assert detail["prior_probability"] == pytest.approx(0.001)
    assert finding.likelihood is not None
    expected = finding.likelihood.posterior_probability(0.001)
    assert posterior.value == pytest.approx(expected)


@pytest.mark.anyio
async def test_the_limitations_text_is_replaced_when_a_posterior_is_shown() -> None:
    """Otherwise the artifact contradicts itself in the same breath.

    The standard text says the library supplies no prior and reports no posterior. A rendered
    posterior sitting beside it would make the page argue with itself.
    """
    finding = await _finding(estimator=_Pricing())
    without = derive_finding(finding)
    with_prior = derive_finding(finding, prior=0.5, prior_supplied_by="the analyst")

    assert with_prior.limitations == PRIOR_LIMITATIONS
    assert "not** the library's" in with_prior.limitations
    assert without.limitations != with_prior.limitations


@pytest.mark.anyio
async def test_the_posterior_comes_from_the_library_rather_than_from_arithmetic_here() -> None:
    """Pinned against the method, because the TypeScript side reimplements it.

    The transform is three lines and duplicated in the browser for the interactive case, so
    the Python value is the reference the goldens are generated from. If this drifted, the
    pinned goldens would be pinning the wrong thing.
    """
    finding = await _finding(estimator=_Pricing())
    ratio = finding.likelihood
    assert ratio is not None

    for prior in (0.1, 0.5, 0.9):
        document = derive_finding(finding, prior=prior)
        node = _kinds(document)[DerivationKind.POSTERIOR][0]
        assert node.value == pytest.approx(ratio.posterior_probability(prior))


# --------------------------------------------------------------------------- #
# Terms, and references into the graph
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_assumptions_and_caveats_are_steps_rather_than_footnotes() -> None:
    """A ratio shown without its caveats is the artifact this library is arranged to prevent."""
    finding = await _finding(estimator=_Pricing())
    document = derive_finding(finding)

    assumptions = _kinds(document)[DerivationKind.ASSUMPTION]
    caveats = _kinds(document)[DerivationKind.CAVEAT]
    assert len(assumptions) == len(finding.assumptions)
    assert len(caveats) == len(finding.caveats)
    assert [node.label for node in assumptions] == list(finding.assumptions)


@pytest.mark.anyio
async def test_every_node_identifier_is_unique() -> None:
    """A renderer keys nodes by id, so a collision would silently merge two steps."""
    finding = await _finding(estimator=_Pricing())
    document = derive_finding(finding, prior=0.5)
    identifiers = [node.id for node in document.root.walk()]
    assert len(identifiers) == len(set(identifiers))


@pytest.mark.anyio
async def test_a_reference_is_carried_whether_or_not_it_resolves() -> None:
    """The derivation does not know what graph is loaded, so it cannot decide.

    ``exists`` stays ``None`` — "nobody has looked" — rather than being set to False, because
    a front end should offer to fetch what is missing rather than reporting nothing there.
    """
    finding = await _finding(estimator=_Pricing())
    document = derive_finding(finding)

    assert document.all_refs
    assert all(reference.exists is None for reference in document.all_refs)
    node_refs = [ref for ref in document.all_refs if ref.kind is GraphRefKind.NODE]
    edge_refs = [ref for ref in document.all_refs if ref.kind is GraphRefKind.EDGE]
    assert any(ref.key.startswith("transaction:bitcoin:") for ref in node_refs)
    assert any(ref.key.startswith("address:bitcoin:") for ref in node_refs)
    assert edge_refs, "the ledger view can address an edge, so an evidence branch can point at one"
    assert {ref.key.split(":")[1] for ref in edge_refs} == {"out"}


@pytest.mark.anyio
async def test_the_claim_identifier_is_stable_across_reordering() -> None:
    """Content-addressed, because the graph overlay groups evidence by claim.

    A positional identifier would silently re-attribute a claim's evidence when the findings
    around it were reordered.
    """
    assert claim_id("a quote", chain_suffix="bitcoin") == claim_id(
        "a quote", chain_suffix="bitcoin"
    )
    assert claim_id("a quote") != claim_id("another quote")
    assert claim_id("a quote", chain_suffix="bitcoin") != claim_id(
        "a quote", chain_suffix="ethereum"
    )


@pytest.mark.anyio
async def test_a_claim_that_never_reduced_still_renders() -> None:
    """Common in practice: no valid address, so nothing could be priced."""
    finding = VerificationFinding(
        post_id="p",
        provenance_strength=ProvenanceStrength.PASTE,
        claim=Claim(type=ClaimType.TRANSFER, quote="q", addresses=("not-an-address",)),
        verdict=ClaimVerdict.INSUFFICIENT_DATA,
        method="transfer",
        reason="the claim could not be reduced to elements that can be checked",
    )
    document = derive_finding(finding)

    assert document.all_refs == (), "there is no chain to point into"
    assert document.node_count >= 3
    assert DerivationKind.BECAUSE in _kinds(document)


@pytest.mark.anyio
async def test_the_infinite_ratio_case_is_stated_rather_than_written_as_a_number() -> None:
    """JSON has no infinity, so the document carries a null and a flag instead.

    A ratio can legitimately be infinite when the coincidence probability is exactly zero.
    Written as a float it would become ``null`` on the wire and read as absent; the flag is
    what says a value exists and is unbounded by the sample.
    """
    finding = await _finding(estimator=_Pricing(base=0.0))
    ratio = finding.likelihood
    assert ratio is not None
    assert ratio.lr == float("inf")

    document = derive_finding(finding)
    ratio_node = _kinds(document)[DerivationKind.LIKELIHOOD_RATIO][0]
    detail = {entry.key: entry.value for entry in ratio_node.detail}

    assert ratio_node.value is None
    assert detail["lr"] is None
    assert detail["lr_at_least"] is True


def test_an_undeclared_scale_is_not_invented() -> None:
    """The band is whatever the library read off the ratio, including ``very strong``."""
    assert VerbalScale.STRONG.value == "strong"
