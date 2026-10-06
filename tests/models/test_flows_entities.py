"""Tests for value-flow nodes and the cluster/evidence vocabulary."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from chainlens.models.entities import Entity, Evidence, HeuristicResult, Label, Merge
from chainlens.models.enums import Chain, EntityKind, FlowDirection, FlowVia, LabelSource
from chainlens.models.flows import AddressRef, EntityRef, NodeRef, ValueFlow
from chainlens.models.primitives import AssetRef

NODE_ADAPTER: TypeAdapter[NodeRef] = TypeAdapter(NodeRef)


# --------------------------------------------------------------------------- #
# NodeRef
# --------------------------------------------------------------------------- #
def test_address_ref_node_key_is_stable_and_namespaced() -> None:
    ref = AddressRef(chain=Chain.BITCOIN, address="bc1qxyz")
    assert ref.node_key == "address:bitcoin:bc1qxyz"
    assert str(ref) == "bc1qxyz"


def test_entity_ref_node_key_uses_the_entity_id_not_the_label() -> None:
    ref = EntityRef(chain=Chain.BITCOIN, entity_id="e1", label="Binance")
    assert ref.node_key == "entity:bitcoin:e1"
    assert str(ref) == "Binance"


def test_entity_ref_falls_back_to_the_id_for_display() -> None:
    assert str(EntityRef(chain=Chain.BITCOIN, entity_id="e1")) == "e1"


def test_node_ref_is_discriminated_by_kind() -> None:
    address = NODE_ADAPTER.validate_python(
        {"kind": "address", "chain": "bitcoin", "address": "bc1q"}
    )
    entity = NODE_ADAPTER.validate_python({"kind": "entity", "chain": "bitcoin", "entity_id": "e1"})
    assert isinstance(address, AddressRef)
    assert isinstance(entity, EntityRef)


def test_unknown_node_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        NODE_ADAPTER.validate_python({"kind": "wallet", "chain": "bitcoin"})


# --------------------------------------------------------------------------- #
# ValueFlow
# --------------------------------------------------------------------------- #
def _flow() -> ValueFlow:
    return ValueFlow(
        chain=Chain.BITCOIN,
        src=AddressRef(chain=Chain.BITCOIN, address="a"),
        dst=EntityRef(chain=Chain.BITCOIN, entity_id="e1", label="Exchange"),
        asset=AssetRef.native(Chain.BITCOIN, symbol="BTC", decimals=8),
        amount=340_000_000,
        n_transfers=3,
        txids=("t1", "t2", "t3"),
        hops=2,
        direction=FlowDirection.OUT,
        via=FlowVia.UTXO,
        path=("address:bitcoin:root", "entity:bitcoin:e1"),
        apportioned=True,
        heuristics=("common-input-ownership",),
    )


def test_value_flow_renders_amount_exactly() -> None:
    assert _flow().amount_to_decimal() == Decimal("3.40000000")


def test_value_flow_edge_key_and_self_loop() -> None:
    flow = _flow()
    assert flow.edge_key == ("address:bitcoin:a", "entity:bitcoin:e1", "native")
    assert not flow.is_self_loop

    ref = AddressRef(chain=Chain.BITCOIN, address="a")
    loop = flow.model_copy(update={"dst": ref})
    assert loop.is_self_loop


def test_value_flow_round_trips_through_json() -> None:
    """A discriminated NodeRef must survive serialisation in both arms."""
    flow = _flow()
    restored = ValueFlow.model_validate_json(flow.model_dump_json())
    assert restored == flow
    assert isinstance(restored.src, AddressRef)
    assert isinstance(restored.dst, EntityRef)


def test_a_flow_s_confidence_cannot_be_anything_but_the_library_s_two_values() -> None:
    """What the range check used to guard, now unrepresentable rather than validated.

    ``confidence`` was ``Field(ge=0.0, le=1.0)`` and this test checked that 1.5 was refused —
    a bound on a number that never had an estimator behind it. It is not a field any more: it
    derives from ``apportioned``, so the only values it can take are 1.0 and 0.5, and a caller
    cannot state a confidence the library did not choose. Stronger than the bound, and for a
    better reason than "it was out of range".
    """
    # `_flow()` is the apportioned one, which is the case this file exists to cover.
    assert _flow().confidence == 0.5
    assert _flow().model_copy(update={"apportioned": False}).confidence == 1.0
    with pytest.raises(ValidationError, match="confidence"):
        ValueFlow(
            chain=Chain.BITCOIN,
            src=AddressRef(chain=Chain.BITCOIN, address="a"),
            dst=AddressRef(chain=Chain.BITCOIN, address="b"),
            asset=AssetRef.native(Chain.BITCOIN),
            amount=1,
            # The point of the test: a field that no longer exists, so the argument is a type
            # error and the assertion is that it is one at runtime too.
            confidence=1.5,  # type: ignore[call-arg]
        )


# --------------------------------------------------------------------------- #
# Merge / Evidence / Entity
# --------------------------------------------------------------------------- #
def _evidence() -> Evidence:
    return Evidence(
        heuristic="common-input-ownership",
        confidence=0.95,
        detail={"input_count": 3},
        txids=("t1",),
    )


def test_merge_requires_at_least_two_addresses() -> None:
    """A merge of one address asserts nothing and must be rejected."""
    with pytest.raises(ValidationError, match="at least two"):
        Merge(addresses=frozenset({"a"}), confidence=0.9, evidence=_evidence())


def test_merge_accepts_two_or_more() -> None:
    merge = Merge(addresses=frozenset({"a", "b"}), confidence=0.9, evidence=_evidence())
    assert merge.addresses == frozenset({"a", "b"})
    assert merge.evidence.txids == ("t1",)


def test_evidence_confidence_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Evidence(heuristic="x", confidence=1.2)


def test_entity_summarises_its_cluster() -> None:
    entity = Entity(
        id="e1",
        chain=Chain.BITCOIN,
        kind=EntityKind.EXCHANGE,
        addresses=frozenset({"a", "b", "c"}),
        labels=(Label(name="Binance", source=LabelSource.PROVIDER, kind=EntityKind.EXCHANGE),),
        confidence=0.8,
        heuristics=("common-input-ownership",),
        evidence=(_evidence(),),
    )
    assert entity.address_count == 3
    assert entity.is_labeled


def test_unlabeled_entity_reports_as_such() -> None:
    entity = Entity(id="e1", chain=Chain.BITCOIN, addresses=frozenset({"a"}))
    assert not entity.is_labeled
    assert entity.kind is EntityKind.UNKNOWN
    assert entity.confidence == 0.0


def test_heuristic_result_emptiness() -> None:
    empty = HeuristicResult(heuristic="change-address")
    assert empty.is_empty
    assert empty.merge_count == 0

    populated = HeuristicResult(
        heuristic="common-input-ownership",
        merges=(Merge(addresses=frozenset({"a", "b"}), confidence=0.9, evidence=_evidence()),),
    )
    assert not populated.is_empty
    assert populated.merge_count == 1


def test_change_flags_are_indexed_by_txid() -> None:
    result = HeuristicResult(
        heuristic="change-address",
        change_flags={"tx1": frozenset({1}), "tx2": frozenset({0, 2})},
    )
    assert result.change_flags["tx2"] == frozenset({0, 2})


def test_label_falls_back_to_unknown_kind() -> None:
    label = Label(name="somewhere", source=LabelSource.USER)
    assert label.kind is EntityKind.UNKNOWN
    assert label.confidence is None
