"""Tests for flow derivation and the graph container.

The apportionment tests carry the most weight: getting a UTXO split wrong is a
quiet way to misstate how much money moved, and the failure would look like a
plausible number rather than an error.
"""

from __future__ import annotations

from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from chainlens.models.enums import Chain, FlowVia
from chainlens.models.flows import (
    AddressRef,
    FlowGraph,
    ValueFlow,
    largest_remainder_split,
    transfers_from_transaction,
)
from chainlens.models.primitives import AssetRef, Transfer
from chainlens.testing.factories import btc_transaction, eth_transaction, inp, out

ALICE, BOB, CAROL = "alice", "bob", "carol"
HUNDRED = 100_000_000


# --------------------------------------------------------------------------- #
# Apportionment
# --------------------------------------------------------------------------- #
def test_split_sums_to_the_total() -> None:
    assert sum(largest_remainder_split(100, [1, 1, 1])) == 100


def test_split_is_proportional() -> None:
    # 100 weighted 3:1 -> 75/25
    assert largest_remainder_split(100, [3, 1]) == [75, 25]


def test_split_breaks_ties_deterministically() -> None:
    """Same input, same output -- otherwise a trace is not reproducible."""
    first = largest_remainder_split(100, [1, 1, 1])
    assert first == largest_remainder_split(100, [1, 1, 1])
    # The leftover unit goes to the lowest index.
    assert first == [34, 33, 33]


def test_split_with_zero_weights_is_an_equal_split() -> None:
    assert largest_remainder_split(100, [0, 0]) == [50, 50]
    assert largest_remainder_split(10, [0, 0, 0]) == [4, 3, 3]


def test_split_of_zero_is_zero() -> None:
    assert largest_remainder_split(0, [5, 5]) == [0, 0]


def test_split_of_nothing_raises_rather_than_returning_nonsense() -> None:
    with pytest.raises(ValueError, match="zero weights"):
        largest_remainder_split(10, [])


@given(
    total=st.integers(min_value=0, max_value=2**255),
    weights=st.lists(st.integers(min_value=0, max_value=10**24), min_size=1, max_size=12),
)
def test_split_always_conserves_the_total(total: int, weights: list[int]) -> None:
    """The invariant the whole apportionment rests on.

    **The bounds are wei-scale and uint256-wide, and the bounds this test used to have are
    why a real defect survived it.** While it drew ``total`` from at most ten million, every
    value was a float's exact integer, and the implementation — which computed the shares as
    ``total * weight / total_weight`` — conserved the total on every example the test could
    generate. Above roughly nine quadrillion a float's mantissa runs out and the truncations
    lose more than one unit each, and the function returned sums that were short by sixty-one
    units or long by two hundred and fifty-six. See its docstring, where the three measured
    cases are written down.
    """
    shares = largest_remainder_split(total, weights)
    assert sum(shares) == total
    assert len(shares) == len(weights)
    assert all(share >= 0 for share in shares)


@pytest.mark.parametrize(
    ("total", "weights"),
    [
        (10**18 + 7, [1, 1, 1]),
        (10**18, [10**18 - 1, 1]),
        (10**19, [1] * 7),
        (2**256 - 1, [1, 1, 1, 1, 1, 1, 1]),
        (10**24, [3, 7, 11, 13]),
    ],
)
def test_split_conserves_the_total_at_wei_scale(total: int, weights: list[int]) -> None:
    """The measured cases, kept as cases rather than only as a hypothesis bound.

    A property test's bounds are a claim about which inputs are interesting, and the failure
    these came from was outside the ones the bounds named. Fixing the bounds fixes the
    strategy; these pin the three values the defect actually produced, so that a regression
    reports the number rather than a shrunk counterexample nobody can read.
    """
    shares = largest_remainder_split(total, weights)
    assert sum(shares) == total, (
        f"the split returned {sum(shares)} for a total of {total}: {sum(shares) - total:+d} units"
    )


@given(
    total=st.integers(min_value=1, max_value=1_000_000),
    weights=st.lists(st.integers(min_value=0, max_value=100), min_size=2, max_size=6),
)
def test_larger_weight_never_gets_a_smaller_share(total: int, weights: list[int]) -> None:
    shares = largest_remainder_split(total, weights)
    paired = sorted(zip(weights, shares, strict=True))
    for (weight_a, share_a), (weight_b, share_b) in pairwise(paired):
        if weight_a <= weight_b:
            assert share_a <= share_b


# --------------------------------------------------------------------------- #
# Account chains
# --------------------------------------------------------------------------- #
def test_an_account_chain_yields_one_native_transfer() -> None:
    transaction = eth_transaction("0xabc", ALICE, BOB, value=100)
    transfers = transfers_from_transaction(transaction)
    assert len(transfers) == 1
    assert (transfers[0].src, transfers[0].dst, transfers[0].amount) == (ALICE, BOB, 100)


def test_a_zero_value_call_yields_no_transfer() -> None:
    """A contract call that moves nothing is not a payment."""
    assert transfers_from_transaction(eth_transaction("0xabc", ALICE, BOB, value=0)) == ()


def test_internal_transfers_are_carried_through() -> None:
    inner = Transfer(
        chain=Chain.ETHEREUM,
        asset=AssetRef.native(Chain.ETHEREUM),
        amount=7,
        txid="0xabc",
        src=BOB,
        dst=CAROL,
    )
    transaction = eth_transaction("0xabc", ALICE, BOB, value=100).model_copy(
        update={"internal_transfers": (inner,)}
    )
    assert inner in transfers_from_transaction(transaction)


# --------------------------------------------------------------------------- #
# UTXO
# --------------------------------------------------------------------------- #
def test_a_single_input_is_attributed_exactly() -> None:
    transaction = btc_transaction(
        "tx1", [out(0, BOB, 60), out(1, ALICE, 40)], [inp(0, ALICE, HUNDRED)]
    )
    transfers = transfers_from_transaction(transaction)
    assert {t.src for t in transfers} == {ALICE}
    assert not any(t.ambiguous for t in transfers)


def test_change_outputs_are_flagged() -> None:
    transaction = btc_transaction(
        "tx1", [out(0, BOB, 60), out(1, ALICE, 40)], [inp(0, ALICE, HUNDRED)]
    )
    transfers = transfers_from_transaction(transaction, change_indexes=frozenset({1}))
    change = next(t for t in transfers if t.dst == ALICE)
    assert change.is_change


def test_a_self_transfer_is_marked_as_change() -> None:
    """Value returning to a sender-controlled address is change by definition."""
    transaction = btc_transaction("tx1", [out(0, ALICE, 40)], [inp(0, ALICE, HUNDRED)])
    assert transfers_from_transaction(transaction)[0].is_change


def test_multi_input_outputs_are_exactly_attributed() -> None:
    """Each output's value is fully split across senders -- this is the guarantee."""
    transaction = btc_transaction(
        "tx1", [out(0, BOB, 100), out(1, CAROL, 60)], [inp(0, ALICE, 100), inp(1, CAROL, 60)]
    )
    transfers = transfers_from_transaction(transaction)
    for destination, expected in ((BOB, 100), (CAROL, 60)):
        received = sum(t.amount for t in transfers if t.dst == destination)
        assert received == expected


def test_multi_input_transfers_are_marked_ambiguous() -> None:
    """Nothing on chain says which input paid which output, and we say so."""
    transaction = btc_transaction("tx1", [out(0, BOB, 100)], [inp(0, ALICE, 60), inp(1, CAROL, 40)])
    assert all(t.ambiguous for t in transfers_from_transaction(transaction))


def test_apportionment_follows_what_each_sender_contributed() -> None:
    transaction = btc_transaction("tx1", [out(0, BOB, 100)], [inp(0, ALICE, 75), inp(1, CAROL, 25)])
    transfers = {t.src: t.amount for t in transfers_from_transaction(transaction)}
    assert transfers == {ALICE: 75, CAROL: 25}


def test_unknown_input_values_fall_back_to_an_equal_split() -> None:
    """Esplora omits input values for unindexed prevouts.

    A partial sum would silently under-weight a sender, so the fallback is an equal
    split and the transfers are marked ambiguous.
    """
    transaction = btc_transaction(
        "tx1", [out(0, BOB, 100)], [inp(0, ALICE, None), inp(1, CAROL, None)]
    )
    transfers = transfers_from_transaction(transaction)
    assert {t.amount for t in transfers} == {50}
    assert all(t.ambiguous for t in transfers)


def test_a_coinbase_has_no_sender() -> None:
    """Inventing a source for minted value would be a fabrication."""
    transaction = btc_transaction("cb", [out(0, ALICE, HUNDRED)], is_coinbase=True)
    transfers = transfers_from_transaction(transaction)
    assert len(transfers) == 1
    assert transfers[0].src is None
    assert transfers[0].via is FlowVia.COINBASE


def test_a_coinbase_with_many_outputs_mints_each_of_them() -> None:
    transaction = btc_transaction("cb", [out(0, ALICE, 10), out(1, BOB, 20)], is_coinbase=True)
    assert {t.dst for t in transfers_from_transaction(transaction)} == {ALICE, BOB}


def test_a_transaction_with_only_unvalued_outputs_yields_nothing() -> None:
    from chainlens.models.primitives import TxOutput

    transaction = btc_transaction("tx1", [TxOutput(index=0, address=BOB, value=None)])
    assert transfers_from_transaction(transaction) == ()


# --------------------------------------------------------------------------- #
# FlowGraph
# --------------------------------------------------------------------------- #
def _edge(src: str, dst: str, amount: int) -> ValueFlow:
    return ValueFlow(
        chain=Chain.BITCOIN,
        src=AddressRef(chain=Chain.BITCOIN, address=src),
        dst=AddressRef(chain=Chain.BITCOIN, address=dst),
        asset=AssetRef.native(Chain.BITCOIN, symbol="BTC", decimals=8),
        amount=amount,
    )


def _graph() -> FlowGraph:
    alice = AddressRef(chain=Chain.BITCOIN, address=ALICE)
    bob = AddressRef(chain=Chain.BITCOIN, address=BOB)
    carol = AddressRef(chain=Chain.BITCOIN, address=CAROL)
    return FlowGraph(
        chain=Chain.BITCOIN,
        seed=alice,
        nodes=(alice, bob, carol),
        edges=(_edge(ALICE, BOB, 30), _edge(ALICE, CAROL, 70)),
    )


def test_graph_accessors() -> None:
    graph = _graph()
    assert graph.node_count == 3
    assert graph.edge_count == 2
    assert not graph.is_empty
    assert graph.total_value() == 100
    assert len(graph.outgoing(f"address:{Chain.BITCOIN}:{ALICE}")) == 2
    assert graph.incoming(f"address:{Chain.BITCOIN}:{BOB}")[0].amount == 30
    assert len(graph.neighbours(f"address:{Chain.BITCOIN}:{ALICE}")) == 2


def test_an_empty_graph_reports_itself_as_empty() -> None:
    graph = FlowGraph(chain=Chain.BITCOIN, seed=AddressRef(chain=Chain.BITCOIN, address=ALICE))
    assert graph.is_empty
    assert graph.total_value() == 0
    assert graph.assets() == ()


def test_a_graph_survives_a_json_round_trip() -> None:
    """A discriminated NodeRef must round-trip inside a container."""
    graph = _graph()
    assert FlowGraph.model_validate_json(graph.model_dump_json()) == graph
