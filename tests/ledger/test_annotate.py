"""Tests for the evidence overlay, and for what an annotation is not allowed to be.

The overlay is a join, so the tests are about *where* things land and what happens to what
does not fit. The annotation tests are about constraint: a person may assert what something
is and never how sure the library should be, and that has to hold structurally rather than by
discipline.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chainlens.ledger.annotate import overlay
from chainlens.ledger.derive import claim_id, finding_refs
from chainlens.ledger.walk import walk_ledger
from chainlens.models.annotate import (
    FORBIDDEN_ANNOTATION_FIELDS,
    Annotation,
    AnnotationKind,
    EvidenceKind,
    annotation_id,
)
from chainlens.models.base import utcnow
from chainlens.models.entities import Entity, Label
from chainlens.models.enums import Chain, EntityKind, LabelSource
from chainlens.models.ledger import LedgerGraph, LedgerPolicy
from chainlens.models.wire import GraphRef, GraphRefKind
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

CAROL = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
ALICE = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
GHOST = "3P14159f73E4gFr7JterCCQh9QjiTjiZrG"
WHEN = datetime(2026, 9, 1, tzinfo=UTC)


class _Pricing:
    async def estimate(self, elements: ClaimElements, *, provider: Provider) -> RateEstimate | None:
        lower, upper = wilson_interval(3, 30_000)
        return RateEstimate(
            component=ComponentEstimate(
                value=1e-4,
                successes=3,
                trials=30_000,
                ci_lower=lower,
                ci_upper=upper,
                method=EstimatorMethod.EMPIRICAL_JOINT,
                population="the sender's own out-of-window transfers",
            ),
            null_model=NullModel.WITHIN_SENDER,
        )


def _provider() -> InMemoryProvider:
    return InMemoryProvider(
        chain=Chain.BITCOIN,
        transactions=[
            btc_transaction("cb0", [out(0, CAROL, 50_000)], is_coinbase=True, block_height=1),
            btc_transaction(
                "tx1",
                [out(0, ALICE, 30_000), out(1, CAROL, 19_500)],
                [inp(0, CAROL, 50_000, prev_txid="cb0", prev_vout=0)],
                block_height=2,
            ),
        ],
    )


async def _graph() -> LedgerGraph:
    return await walk_ledger(_provider(), seed_address=CAROL, policy=LedgerPolicy(max_depth=2))


async def _finding() -> VerificationFinding:
    post = Post(
        id="1",
        text="carol moved ~30,000 sats to alice",
        source=SourceRef(strength=ProvenanceStrength.PRINTOUT, captured_at=utcnow()),
    )
    claim = Claim(
        type=ClaimType.TRANSFER,
        quote=post.text,
        addresses=(CAROL, ALICE),
        amount_text="~30,000 sats",
    )
    engine = VerificationEngine(_provider(), estimator=_Pricing())
    report = await engine.verify_post(post, Extraction(claims=(claim,)))
    return report.findings[0]


def _node_ref(address: str) -> GraphRef:
    return GraphRef(kind=GraphRefKind.NODE, key=f"address:{Chain.BITCOIN}:{address}")


def _annotation(target: GraphRef, assertion: str = "a known exchange") -> Annotation:
    return Annotation.create(
        target=target,
        kind=AnnotationKind.EXCHANGE,
        assertion=assertion,
        author="pm",
        basis="listed by the venue",
        created_at=WHEN,
    )


# --------------------------------------------------------------------------- #
# Where a finding lands
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_a_finding_lands_on_its_endpoints_its_transaction_and_its_edge() -> None:
    """The edge is the part only this view can name.

    ``ValueFlow`` keeps only its first contributor's index, so a flow edge cannot point at
    one output; ``tx1:out:0`` can, and that is what lets a reader go from a claim to the
    exact movement it rests on.
    """
    graph = await _graph()
    result = overlay(graph, findings=(await _finding(),))

    assert f"address:bitcoin:{ALICE}" in result.by_node
    assert f"address:bitcoin:{CAROL}" in result.by_node
    assert "transaction:bitcoin:tx1" in result.by_node
    assert "tx1:out:0" in result.by_edge
    assert result.unjoined == ()


@pytest.mark.anyio
async def test_every_placed_reference_is_marked_as_present() -> None:
    """After a join, "not found here" is a fact rather than an unasked question."""
    result = overlay(await _graph(), findings=(await _finding(),))
    item = result.by_node[f"address:bitcoin:{ALICE}"][0]
    assert all(ref.exists is True for ref in item.graph_refs)


@pytest.mark.anyio
async def test_a_finding_is_one_item_not_one_per_node() -> None:
    """A finding is one assertion; splitting it would lose what belongs together."""
    result = overlay(await _graph(), findings=(await _finding(),))
    for items in result.by_node.values():
        assert all(item.kind is EvidenceKind.FINDING for item in items)
    assert len(result.by_node[f"address:bitcoin:{ALICE}"]) == 1


@pytest.mark.anyio
async def test_the_claim_identifier_maps_to_everything_it_touches() -> None:
    """So selecting a claim in one view can highlight it in the other."""
    finding = await _finding()
    result = overlay(await _graph(), findings=(finding,))

    expected = claim_id(finding.claim.quote, chain_suffix=Chain.BITCOIN.value)
    assert set(result.claim_refs) == {expected}
    assert {ref.key for ref in result.claim_refs[expected]} == {
        ref.key for ref in finding_refs(finding)
    }


@pytest.mark.anyio
async def test_the_item_carries_the_finding_s_own_wording() -> None:
    """A renderer must not have to compose a summary from fields, or it will compose one."""
    finding = await _finding()
    result = overlay(await _graph(), findings=(finding,))
    item = result.by_node[f"address:bitcoin:{ALICE}"][0]

    detail = {entry.key: entry.value for entry in item.detail}
    assert detail["verdict"] == finding.verdict.value
    assert detail["quote"] == finding.claim.quote
    assert detail["method"] == finding.method
    assert item.claim_id is not None


# --------------------------------------------------------------------------- #
# What does not fit
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_evidence_about_an_absent_node_is_reported_rather_than_dropped() -> None:
    """The whole reason the join is not left to a renderer.

    A claim about an address outside the walked window is a real and common case, and
    dropping it would make the graph look complete.
    """
    result = overlay(await _graph(), annotations=(_annotation(_node_ref(GHOST)),))

    assert result.unjoined
    assert result.unjoined[0].key == f"address:bitcoin:{GHOST}"
    assert result.unjoined[0].exists is False
    assert "not in this document" in (result.unjoined[0].note or "")
    assert not result.has_annotations, "an unplaced annotation is not on the graph"


@pytest.mark.anyio
async def test_a_label_lands_on_its_address_and_keeps_its_source() -> None:
    """Whose assertion it is survives the join, because the two look identical otherwise."""
    label = Label(name="Binance", source=LabelSource.PROVIDER, kind=EntityKind.EXCHANGE)
    result = overlay(await _graph(), labels={ALICE: (label,)})

    item = result.by_node[f"address:bitcoin:{ALICE}"][0]
    assert item.kind is EvidenceKind.LABEL
    assert item.source is LabelSource.PROVIDER
    assert "Binance" in item.summary


@pytest.mark.anyio
async def test_a_cluster_is_evidence_about_its_members_not_a_node_of_its_own() -> None:
    """This view never merges addresses into an entity.

    The merge is a hypothesis, and hiding the addresses behind it would hide the thing a
    reader came to look at.
    """
    entity = Entity(
        id="e1",
        chain=Chain.BITCOIN,
        addresses=frozenset({CAROL, ALICE}),
        confidence=0.95,
        heuristics=("common-input-ownership",),
    )
    result = overlay(await _graph(), entities=(entity,))

    assert f"address:bitcoin:{ALICE}" in result.by_node
    assert f"address:bitcoin:{CAROL}" in result.by_node
    assert not any(key.startswith("entity:") for key in result.by_node)
    item = result.by_node[f"address:bitcoin:{ALICE}"][0]
    assert item.kind is EvidenceKind.ENTITY
    assert item.confidence == 0.95


@pytest.mark.anyio
async def test_a_cluster_member_outside_the_walk_is_reported_once() -> None:
    entity = Entity(id="e1", chain=Chain.BITCOIN, addresses=frozenset({ALICE, GHOST}))
    result = overlay(await _graph(), entities=(entity,))
    assert [ref.key for ref in result.unjoined] == [f"address:bitcoin:{GHOST}"]


@pytest.mark.anyio
async def test_too_many_unjoined_references_are_summarised_rather_than_listed() -> None:
    """A list nobody reads is a list that hides the entry that mattered."""
    many = tuple(
        _annotation(
            GraphRef(kind=GraphRefKind.NODE, key=f"address:bitcoin:absent{position}"),
            assertion=f"assertion {position}",
        )
        for position in range(250)
    )
    result = overlay(await _graph(), annotations=many)

    assert len(result.unjoined) == 200
    assert any("250 references are not in this document" in note for note in result.warnings)


# --------------------------------------------------------------------------- #
# The join is a pure function
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_the_overlay_does_not_touch_the_graph_it_joins_onto() -> None:
    """Nothing an annotation says can change a measured field.

    The overlay returns items; it never rewrites the document. So an assertion about what an
    address *is* cannot alter what the chain recorded it *did* — which is the property that
    keeps a declared label from quietly becoming a measurement.
    """
    graph = await _graph()
    before = graph.model_dump_json()
    annotations = (_annotation(_node_ref(ALICE), "actually a cold wallet"),)

    overlay(graph, annotations=annotations)

    assert graph.model_dump_json() == before


@pytest.mark.anyio
async def test_the_same_inputs_give_the_same_overlay() -> None:
    graph = await _graph()
    finding = await _finding()
    label = Label(name="Binance", source=LabelSource.PROVIDER)

    first = overlay(graph, findings=(finding,), labels={ALICE: (label,)})
    second = overlay(graph, findings=(finding,), labels={ALICE: (label,)})
    assert first == second


@pytest.mark.anyio
async def test_an_overlay_with_nothing_to_join_is_empty_rather_than_absent() -> None:
    result = overlay(await _graph())
    assert result.item_count == 0
    assert result.covered_keys == ()
    assert result.unjoined == ()
    assert not result.has_annotations


# --------------------------------------------------------------------------- #
# What an annotation is not allowed to be
# --------------------------------------------------------------------------- #
def test_an_annotation_has_no_field_that_could_hold_a_measurement() -> None:
    """Pinned rather than promised.

    These are the fields through which a declared assertion would start to look like a
    measurement, and the surest way to keep them out is for the model not to have them.
    """
    assert not (set(Annotation.model_fields) & FORBIDDEN_ANNOTATION_FIELDS)


def test_an_annotation_declares_itself_as_a_user_assertion() -> None:
    assert _annotation(_node_ref(ALICE)).source is LabelSource.USER


def test_an_annotation_cannot_claim_a_source_it_is_not() -> None:
    """Provider evidence arrives through the overlay, not by writing it into an annotation."""
    with pytest.raises(ValueError, match="cannot claim another source"):
        Annotation(
            id="x",
            created_at=WHEN,
            author="pm",
            basis="a source",
            target=_node_ref(ALICE),
            kind=AnnotationKind.EXCHANGE,
            assertion="an exchange",
            source=LabelSource.PROVIDER,
        )


def _bare_annotation(**overrides: object) -> Annotation:
    """An annotation with everything filled in, so a test can vary one field."""
    fields: dict[str, object] = {
        "id": "x",
        "created_at": WHEN,
        "author": "pm",
        "basis": "a stated ground",
        "target": _node_ref(ALICE),
        "kind": AnnotationKind.NOTE,
        "assertion": "something",
    }
    return Annotation(**{**fields, **overrides})  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["author", "basis", "assertion"])
def test_an_empty_field_is_refused_at_the_field(field: str) -> None:
    """Two guards, and they are not the same guard.

    An empty string is a malformed field, which the type catches. Whitespace is *well formed
    and semantically empty* — ``"   "`` is a string, and it is not a name — which is what the
    validator catches. One check for both would either let whitespace through as an author or
    reject it with a message about string length.
    """
    with pytest.raises(ValueError, match="at least 1 character"):
        _bare_annotation(**{field: ""})


@pytest.mark.parametrize(
    ("field", "expected"), [("author", "name who asserted"), ("basis", "state the basis")]
)
def test_whitespace_is_not_an_owner_and_not_a_ground(field: str, expected: str) -> None:
    with pytest.raises(ValueError, match=expected):
        _bare_annotation(**{field: "   "})


def test_an_annotation_identifier_is_content_addressed() -> None:
    """Re-recording the same assertion is idempotent; changing it is visibly a new record."""
    first = _annotation(_node_ref(ALICE), "a known exchange")
    same = _annotation(_node_ref(ALICE), "a known exchange")
    changed = _annotation(_node_ref(ALICE), "a cold wallet")

    assert first.id == same.id
    assert first.id != changed.id
    assert annotation_id(
        target=_node_ref(ALICE), kind=AnnotationKind.EXCHANGE, assertion="a", author="pm"
    ).startswith("annotation:")


def test_an_annotation_on_an_edge_is_addressable() -> None:
    """A single movement can carry a declaration, which the flow view cannot express."""
    target = GraphRef(kind=GraphRefKind.EDGE, key="tx1:out:0")
    assert _annotation(target).target.kind is GraphRefKind.EDGE


@pytest.mark.anyio
async def test_an_annotation_reaches_the_graph_marked_as_user_declared() -> None:
    """The distinction has to survive being separated from the panel that produced it."""
    annotation = _annotation(_node_ref(ALICE))
    result = overlay(await _graph(), annotations=(annotation,))

    item = result.by_node[f"address:bitcoin:{ALICE}"][0]
    assert item.kind is EvidenceKind.ANNOTATION
    assert item.source is LabelSource.USER
    assert item.confidence is None, "a declared assertion carries no confidence at all"
    assert "user-declared" in item.summary
