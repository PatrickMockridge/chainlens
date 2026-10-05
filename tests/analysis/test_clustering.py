"""Tests for the clusterer: evidence, refusals, confidence and stability."""

from __future__ import annotations

import pytest

from chainlens.analysis.clustering import Clusterer
from chainlens.exceptions import AnalysisError
from chainlens.models.entities import Evidence, HeuristicResult, Merge
from chainlens.models.enums import Chain
from chainlens.models.primitives import Transaction
from chainlens.testing.factories import btc_transaction, inp, out

ALICE, BOB, CAROL, DAVE = "alice", "bob", "carol", "dave"


def _merge(*addresses: str, confidence: float = 0.9, heuristic: str = "test") -> Merge:
    return Merge(
        addresses=frozenset(addresses),
        confidence=confidence,
        evidence=Evidence(heuristic=heuristic, confidence=confidence, detail={}),
    )


# --------------------------------------------------------------------------- #
# Applying evidence
# --------------------------------------------------------------------------- #
def test_a_merge_unions_and_records_evidence() -> None:
    clusterer = Clusterer()
    assert clusterer.apply_merge(_merge(ALICE, BOB))
    assert clusterer.members(ALICE) == frozenset({ALICE, BOB})
    assert len(clusterer.applied_merges) == 1
    assert clusterer.heuristics_applied == frozenset({"test"})


def test_a_merge_of_many_addresses_unions_them_all() -> None:
    clusterer = Clusterer()
    clusterer.apply_merge(_merge(ALICE, BOB, CAROL))
    assert clusterer.members(CAROL) == frozenset({ALICE, BOB, CAROL})


def test_union_helper_builds_its_own_evidence() -> None:
    clusterer = Clusterer()
    assert clusterer.union(ALICE, BOB, confidence=0.7, heuristic="cio", detail={"n": 2})
    assert clusterer.members(ALICE) == frozenset({ALICE, BOB})
    assert clusterer.applied_merges[0][1].detail == {"n": 2}


def test_apply_runs_a_heuristic_result() -> None:
    clusterer = Clusterer()
    result = HeuristicResult(heuristic="cio", merges=(_merge(ALICE, BOB), _merge(CAROL, DAVE)))
    applied = clusterer.apply(result)
    assert applied.merges_applied == 2
    assert applied.merges_refused == 0


# --------------------------------------------------------------------------- #
# Refusing conflicts
# --------------------------------------------------------------------------- #
def test_a_declared_non_equivalence_blocks_a_merge() -> None:
    clusterer = Clusterer([(ALICE, BOB, "known different entities")])
    assert clusterer.apply_merge(_merge(ALICE, BOB)) is False
    assert clusterer.members(ALICE) == frozenset({ALICE})
    assert clusterer.refusals[0].reason == "known different entities"


def test_a_conflict_is_judged_against_the_resulting_cluster() -> None:
    """Merging into a cluster that already contains the blocked address is a conflict.

    Checking only the incoming edge would let a conflict be laundered through an
    intermediate merge.
    """
    clusterer = Clusterer([(ALICE, CAROL, "different entities")])
    clusterer.apply_merge(_merge(BOB, CAROL))
    assert clusterer.members(BOB) == frozenset({BOB, CAROL})
    # BOB is now in CAROL's cluster, so BOB cannot join ALICE either.
    assert clusterer.apply_merge(_merge(ALICE, BOB)) is False
    assert clusterer.members(ALICE) == frozenset({ALICE})


def test_a_refusal_does_not_raise() -> None:
    """A forbidden merge is a finding to report, not a crash."""
    clusterer = Clusterer([(ALICE, BOB, "different")])
    result = HeuristicResult(heuristic="test", merges=(_merge(ALICE, BOB),))
    applied = clusterer.apply(result)  # must not raise
    assert applied.merges_refused == 1
    assert applied.merges_applied == 0


def test_declaring_an_address_non_equivalent_to_itself_is_an_error() -> None:
    with pytest.raises(AnalysisError):
        Clusterer([(ALICE, ALICE, "nonsense")])


def test_blocked_pairs_are_exposed() -> None:
    clusterer = Clusterer([(ALICE, BOB, "different")])
    assert list(clusterer.blocked_pairs.values()) == ["different"]


# --------------------------------------------------------------------------- #
# Confidence
# --------------------------------------------------------------------------- #
def test_cluster_confidence_is_the_weakest_link() -> None:
    """An average would overstate a cluster built from one strong and one weak merge."""
    clusterer = Clusterer()
    clusterer.apply_merge(_merge(ALICE, BOB, confidence=0.95))
    clusterer.apply_merge(_merge(BOB, CAROL, confidence=0.55))
    members = clusterer.members(ALICE)
    assert clusterer.confidence_for(members) == 0.55


def test_a_lone_address_has_no_confidence() -> None:
    assert Clusterer().confidence_for(frozenset({ALICE})) == 0.0


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #
def test_entities_are_built_for_clusters_of_two_or_more() -> None:
    """A lone address yields no entity: there is nothing to assert about it."""
    clusterer = Clusterer()
    clusterer.apply_merge(_merge(ALICE, BOB))
    clusterer.union_find.add(CAROL)  # a cluster of one
    entities = clusterer.entities(chain=Chain.BITCOIN)
    assert len(entities) == 1
    assert entities[0].addresses == frozenset({ALICE, BOB})


def test_entity_ids_are_stable_across_runs_and_instances() -> None:
    """Reports must be reproducible: the same cluster gets the same id."""
    first = Clusterer()
    first.apply_merge(_merge(ALICE, BOB))
    second = Clusterer()
    second.apply_merge(_merge(ALICE, BOB, confidence=0.5))

    id_a = first.entities(chain=Chain.BITCOIN)[0].id
    id_b = second.entities(chain=Chain.BITCOIN)[0].id
    assert id_a == id_b


def test_entity_ids_differ_for_different_clusters() -> None:
    left = Clusterer()
    left.apply_merge(_merge(ALICE, BOB))
    right = Clusterer()
    right.apply_merge(_merge(ALICE, CAROL))
    assert left.cluster_id(left.members(ALICE)) != right.cluster_id(right.members(ALICE))


def test_an_entity_carries_only_its_own_evidence() -> None:
    """Evidence from an unrelated cluster must not leak into this entity."""
    clusterer = Clusterer()
    clusterer.apply_merge(_merge(ALICE, BOB, heuristic="cio"))
    clusterer.apply_merge(_merge(CAROL, DAVE, heuristic="eth-deposit-address"))

    entities = clusterer.entities(chain=Chain.BITCOIN)
    alice_entity = next(entity for entity in entities if ALICE in entity.addresses)
    assert alice_entity.heuristics == ("cio",)
    assert all(item.heuristic == "cio" for item in alice_entity.evidence)


def test_labels_are_attached_to_the_address_they_belong_to() -> None:
    from chainlens.models.entities import Label
    from chainlens.models.enums import LabelSource

    clusterer = Clusterer()
    clusterer.apply_merge(_merge(ALICE, BOB))
    label = Label(name="Binance", source=LabelSource.PROVIDER, address=BOB)
    entity = clusterer.entities(chain=Chain.BITCOIN, labels={BOB: (label,)})[0]
    assert entity.labels == (label,)
    assert entity.is_labeled


# --------------------------------------------------------------------------- #
# Folding change outputs
# --------------------------------------------------------------------------- #
def _spend() -> Transaction:
    """A transaction from a single sender paying a recipient and a change output."""
    return btc_transaction(
        "tx1",
        [out(0, "merchant", 60), out(1, "alice-change", 40)],
        [inp(0, ALICE, 100, prev_txid="prev", prev_vout=0)],
    )


def test_a_change_output_is_folded_into_the_senders_cluster() -> None:
    """Leaving it out would fragment one wallet into a cluster per transaction."""
    clusterer = Clusterer()
    transaction = _spend()
    folded = clusterer.fold_change_outputs(
        {transaction.txid: transaction}, {transaction.txid: frozenset({1})}
    )
    assert folded == 1
    assert clusterer.members(ALICE) == frozenset({ALICE, "alice-change"})
    # The payment output is not change and must stay out of the cluster.
    assert "merchant" not in clusterer.members(ALICE)


def test_folding_ignores_unknown_transactions() -> None:
    assert Clusterer().fold_change_outputs({}, {"missing": frozenset({0})}) == 0


def test_folding_ignores_an_output_index_that_does_not_exist() -> None:
    transaction = _spend()
    folded = Clusterer().fold_change_outputs(
        {transaction.txid: transaction}, {transaction.txid: frozenset({99})}
    )
    assert folded == 0


def test_change_flags_never_merge_the_payment_recipient() -> None:
    """The whole risk of folding: pulling a merchant into the payer's cluster."""
    clusterer = Clusterer()
    transaction = _spend()
    clusterer.fold_change_outputs(
        {transaction.txid: transaction}, {transaction.txid: frozenset({1})}
    )
    assert "merchant" not in clusterer.members(ALICE)
