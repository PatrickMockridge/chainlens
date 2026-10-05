"""Tests for the ledger walk: transactions and addresses, unaggregated.

The properties under test are the ones that distinguish this view from the tracer's, so
several of them are deliberately the *opposite* of an existing tracer test — two
transfers on one pair are two edges here and one aggregated edge there, and a coinbase is
a drawable node here and cannot be drawn there at all.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from chainlens.exceptions import CapabilityError
from chainlens.ledger.walk import (
    BUDGET_EDGES,
    BUDGET_NODES,
    FRONTIER_DEFERRED,
    POLICY_COINBASE,
    POLICY_MAX_FAN_OUT,
    POLICY_MIN_VALUE,
    walk_ledger,
)
from chainlens.models.enums import Chain, Direction
from chainlens.models.ledger import (
    AmountStatus,
    LedgerAddressNode,
    LedgerEdgeRole,
    LedgerGraph,
    LedgerPolicy,
    LedgerTransactionNode,
    LedgerUnparsedNode,
    address_node_key,
    transaction_node_key,
    unparsed_node_key,
)
from chainlens.models.primitives import Transaction
from chainlens.providers.capabilities import Capability
from chainlens.testing.factories import btc_transaction, inp, out
from chainlens.testing.in_memory import InMemoryProvider

ALICE, BOB, CAROL = "alice", "bob", "carol"
WHEN = datetime(2026, 9, 10, tzinfo=UTC)


def _linear() -> InMemoryProvider:
    """alice -> bob -> carol, one transaction each."""
    return InMemoryProvider(
        chain=Chain.BITCOIN,
        transactions=[
            btc_transaction(
                "tx1", [out(0, BOB, 60)], [inp(0, ALICE, 60)], block_height=1, block_time=WHEN
            ),
            btc_transaction(
                "tx2", [out(0, CAROL, 60)], [inp(0, BOB, 60)], block_height=2, block_time=WHEN
            ),
        ],
    )


def _provider(*transactions: Transaction) -> InMemoryProvider:
    return InMemoryProvider(chain=Chain.BITCOIN, transactions=transactions)


async def _walk(provider: InMemoryProvider, seed: str = ALICE, **kwargs: Any) -> LedgerGraph:
    return await walk_ledger(provider, seed_address=seed, **kwargs)


# --------------------------------------------------------------------------- #
# The shape
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_a_transaction_is_a_node_and_an_address_is_a_node() -> None:
    graph = await _walk(_linear(), policy=LedgerPolicy(max_depth=2))
    kinds = {node.kind for node in graph.nodes}
    assert kinds == {"address", "transaction"}
    assert graph.transaction_count == 2
    assert graph.address_count == 3


@pytest.mark.anyio
async def test_every_edge_is_one_recorded_input_or_output() -> None:
    graph = await _walk(_linear(), policy=LedgerPolicy(max_depth=2))
    assert graph.edge_count == 4
    assert {edge.role for edge in graph.edges} == {LedgerEdgeRole.INPUT, LedgerEdgeRole.OUTPUT}
    assert {edge.key for edge in graph.edges} == {
        "tx1:in:0",
        "tx1:out:0",
        "tx2:in:0",
        "tx2:out:0",
    }


@pytest.mark.anyio
async def test_an_input_runs_address_to_transaction_and_an_output_the_other_way() -> None:
    graph = await _walk(_linear(), policy=LedgerPolicy(max_depth=2))
    alice = address_node_key(Chain.BITCOIN, ALICE)
    tx1 = transaction_node_key(Chain.BITCOIN, "tx1")
    funded = graph.edges[0]

    assert (funded.src, funded.dst) == (alice, tx1)
    assert (graph.edges[1].src, graph.edges[1].dst) == (tx1, address_node_key(Chain.BITCOIN, BOB))


@pytest.mark.anyio
async def test_two_transfers_on_one_pair_stay_two_edges() -> None:
    """The opposite of the tracer, which folds them into one edge with ``n_transfers``.

    Folding is what makes the flow view readable and what destroys the per-output detail
    this view exists for.
    """
    provider = _provider(
        btc_transaction("tx1", [out(0, BOB, 10)], [inp(0, ALICE, 10)], block_height=1),
        btc_transaction("tx2", [out(0, BOB, 20)], [inp(0, ALICE, 20)], block_height=2),
    )
    graph = await _walk(provider, policy=LedgerPolicy(max_depth=1))

    outputs = [edge for edge in graph.edges if edge.role is LedgerEdgeRole.OUTPUT]
    assert len(outputs) == 2
    assert [edge.amount for edge in outputs] == [10, 20]
    assert graph.transaction_count == 2


# --------------------------------------------------------------------------- #
# What the flow view cannot represent
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_a_coinbase_is_a_node_with_no_input_edges() -> None:
    """Not a dropped transfer and not a fabricated miner: a transaction that mints.

    This is the case a ``FlowGraph`` cannot draw at all, because its edges need a source
    node and minted value has no address to come from.
    """
    provider = _provider(
        btc_transaction("cb", [out(0, ALICE, 500)], is_coinbase=True, block_height=1)
    )
    graph = await _walk(provider, policy=LedgerPolicy(max_depth=1))

    node = graph.node(transaction_node_key(Chain.BITCOIN, "cb"))
    assert isinstance(node, LedgerTransactionNode)
    assert node.is_coinbase
    assert graph.incoming(node.key) == ()
    assert [edge.amount for edge in graph.outgoing(node.key)] == [500]


@pytest.mark.anyio
async def test_a_coinbase_can_be_left_out_by_policy_but_is_kept_by_default() -> None:
    """The exclusion acts on the *transaction*, because a coinbase usually has no inputs.

    Skipping coinbase-marked inputs instead would leave a transaction that still looks
    minted and has no inputs — the misreading this view exists to prevent, manufactured
    by the policy meant to prevent it.
    """
    provider = _provider(
        btc_transaction("cb", [out(0, ALICE, 500)], is_coinbase=True, block_height=1)
    )
    kept = await _walk(provider, policy=LedgerPolicy(max_depth=1, include_coinbase=True))
    dropped = await _walk(provider, policy=LedgerPolicy(max_depth=1, include_coinbase=False))

    assert kept.transaction_count == 1
    assert dropped.transaction_count == 0
    assert dropped.stop_reasons.get(POLICY_COINBASE, 0) >= 1


@pytest.mark.anyio
async def test_an_esplora_style_coinbase_is_excluded_the_same_way() -> None:
    """Esplora reports one input with a null prevout rather than an empty list.

    Both shapes mean the same thing, and the policy has to treat them the same or the
    same flag behaves differently on the same chain depending on the provider.
    """
    provider = _provider(
        btc_transaction(
            "cb",
            [out(0, ALICE, 500)],
            [inp(0, None, is_coinbase=True)],
            is_coinbase=True,
            block_height=1,
        )
    )
    dropped = await _walk(provider, policy=LedgerPolicy(max_depth=1, include_coinbase=False))
    kept = await _walk(provider, policy=LedgerPolicy(max_depth=1, include_coinbase=True))

    assert dropped.transaction_count == 0
    assert kept.transaction_count == 1
    node = kept.node(transaction_node_key(Chain.BITCOIN, "cb"))
    assert isinstance(node, LedgerTransactionNode)
    assert node.is_coinbase


@pytest.mark.anyio
async def test_an_output_with_no_address_gets_a_node_rather_than_vanishing() -> None:
    """An OP_RETURN is a real output with a real value.

    Dropping it would leave a transaction whose drawn edges do not add up, and the graph
    would misstate the transaction rather than merely simplify it.
    """
    provider = _provider(
        btc_transaction(
            "tx1",
            [out(0, BOB, 90), out(1, None, 5)],
            [inp(0, ALICE, 95)],
            block_height=1,
        )
    )
    graph = await _walk(provider, policy=LedgerPolicy(max_depth=1))

    unparsed = graph.node(unparsed_node_key(Chain.BITCOIN, "tx1"))
    assert isinstance(unparsed, LedgerUnparsedNode)
    assert unparsed.edge_count == 1
    assert unparsed.total_value == 5

    assert {edge.key for edge in graph.outgoing(transaction_node_key(Chain.BITCOIN, "tx1"))} == {
        "tx1:out:0",
        "tx1:out:1",
    }


@pytest.mark.anyio
async def test_an_unrecorded_input_value_is_unknown_and_never_a_zero() -> None:
    """Esplora's ``vin`` often omits the value, and inventing one corrupts every total.

    The flow view folds this into an apportionment. Here it stays unknown, and the
    transaction's input total becomes ``None`` rather than a partial sum.
    """
    provider = _provider(btc_transaction("tx1", [out(0, BOB, 60)], [inp(0, ALICE)], block_height=1))
    graph = await _walk(provider, policy=LedgerPolicy(max_depth=1))

    funding = graph.edges[0]
    assert funding.amount is None
    assert funding.amount_status is AmountStatus.MISSING
    assert funding.is_unknown_amount

    node = graph.node(transaction_node_key(Chain.BITCOIN, "tx1"))
    assert isinstance(node, LedgerTransactionNode)
    assert node.total_input_value is None
    assert not node.value_complete
    assert graph.unknown_amount_count == 1


# --------------------------------------------------------------------------- #
# Change and CoinJoin
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_change_is_flagged_and_kept() -> None:
    """A viewer that hides change hides how value comes back, which is often the point."""
    provider = _provider(
        btc_transaction(
            "tx1", [out(0, BOB, 60), out(1, ALICE, 40)], [inp(0, ALICE, 100)], block_height=1
        )
    )
    graph = await _walk(provider, policy=LedgerPolicy(max_depth=1))

    change = [edge for edge in graph.edges if edge.is_change]
    assert len(change) == 1
    assert change[0].amount == 40
    assert change[0].role is LedgerEdgeRole.OUTPUT


@pytest.mark.anyio
async def test_change_can_be_excluded_by_policy_without_being_mislabelled() -> None:
    provider = _provider(
        btc_transaction(
            "tx1", [out(0, BOB, 60), out(1, ALICE, 40)], [inp(0, ALICE, 100)], block_height=1
        )
    )
    graph = await _walk(provider, policy=LedgerPolicy(max_depth=1, include_change=False))
    assert all(not edge.is_change for edge in graph.edges)
    assert len(graph.edges) == 2


@pytest.mark.anyio
async def test_a_coinjoin_is_marked_because_reading_through_it_is_most_wrong() -> None:
    """Three inputs and three equal outputs: the library's own CoinJoin rule."""
    provider = _provider(
        btc_transaction(
            "cj",
            [out(0, ALICE, 10), out(1, BOB, 10), out(2, CAROL, 10)],
            [inp(0, ALICE, 10), inp(1, BOB, 10), inp(2, CAROL, 10)],
            block_height=1,
        )
    )
    graph = await _walk(provider, policy=LedgerPolicy(max_depth=1))

    node = graph.node(transaction_node_key(Chain.BITCOIN, "cj"))
    assert isinstance(node, LedgerTransactionNode)
    assert node.is_coinjoin


@pytest.mark.anyio
async def test_an_ordinary_transaction_is_not_marked_as_a_coinjoin() -> None:
    graph = await _walk(_linear(), policy=LedgerPolicy(max_depth=1))
    nodes = [node for node in graph.nodes if isinstance(node, LedgerTransactionNode)]
    assert all(not node.is_coinjoin for node in nodes)


# --------------------------------------------------------------------------- #
# Direction, depth and the frontier
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_direction_decides_what_expands_and_never_what_is_drawn() -> None:
    """A transaction node showing only its outgoing side would look like a coinbase."""
    outward = await _walk(_linear(), policy=LedgerPolicy(max_depth=1), direction=Direction.OUT)
    inward = await _walk(_linear(), policy=LedgerPolicy(max_depth=1), direction=Direction.IN)

    # Outward reaches bob's transaction; inward reaches nothing upstream of alice.
    assert outward.transaction_count == 1
    assert inward.transaction_count == 1
    # Both draw the whole of the one transaction they hold, inputs included.
    assert {edge.role for edge in outward.edges} == {
        LedgerEdgeRole.INPUT,
        LedgerEdgeRole.OUTPUT,
    }


@pytest.mark.anyio
async def test_depth_limits_expansion_and_puts_the_rest_on_the_frontier() -> None:
    """A live view expands the frontier; a truncation would be a different thing."""
    graph = await _walk(_linear(), policy=LedgerPolicy(max_depth=1), direction=Direction.OUT)

    assert graph.transaction_count == 1
    assert graph.frontier == (address_node_key(Chain.BITCOIN, BOB),)
    assert graph.stop_reasons == {FRONTIER_DEFERRED: 1}
    assert not graph.truncated, "stopping at the requested depth is not a truncation"


@pytest.mark.anyio
async def test_a_deeper_walk_reaches_further_and_empties_the_frontier() -> None:
    graph = await _walk(_linear(), policy=LedgerPolicy(max_depth=2), direction=Direction.OUT)
    assert graph.transaction_count == 2
    assert graph.frontier == (address_node_key(Chain.BITCOIN, CAROL),)


@pytest.mark.anyio
async def test_a_self_paying_address_is_not_chased_by_default() -> None:
    graph = await _walk(_linear(), policy=LedgerPolicy(max_depth=3))
    addresses = [node for node in graph.nodes if isinstance(node, LedgerAddressNode)]
    assert all(address.depth is not None for address in addresses)
    seed = graph.node(address_node_key(Chain.BITCOIN, ALICE))
    assert isinstance(seed, LedgerAddressNode)
    assert seed.is_seed


# --------------------------------------------------------------------------- #
# Budgets and policy, reported rather than silent
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_a_node_budget_truncates_and_says_so() -> None:
    graph = await _walk(_linear(), policy=LedgerPolicy(max_depth=2, max_nodes=3))
    assert graph.truncated
    assert graph.stop_reasons.get(BUDGET_NODES, 0) >= 1


@pytest.mark.anyio
async def test_an_edge_budget_truncates_and_says_so() -> None:
    # Two edges fit and the third is refused: alice expands, bob does not, so the
    # walk needs max_depth 2 to have a third edge to refuse.
    graph = await _walk(_linear(), policy=LedgerPolicy(max_depth=2, max_edges=2))
    assert graph.truncated
    assert graph.stop_reasons.get(BUDGET_EDGES, 0) >= 1
    assert graph.edge_count == 2


@pytest.mark.anyio
async def test_a_value_floor_drops_edges_and_counts_them() -> None:
    provider = _provider(
        btc_transaction(
            "tx1",
            [out(0, BOB, 1_000_000), out(1, CAROL, 100)],
            [inp(0, ALICE, 1_000_100)],
            block_height=1,
        )
    )
    graph = await _walk(provider, policy=LedgerPolicy(max_depth=1, min_value=10_000))

    assert graph.stop_reasons.get(POLICY_MIN_VALUE, 0) >= 1
    assert "tx1:out:1" not in {edge.key for edge in graph.edges}
    assert graph.node(address_node_key(Chain.BITCOIN, CAROL)) is None


@pytest.mark.anyio
async def test_a_transaction_with_too_many_outputs_is_collapsed_not_quietly_shrunk() -> None:
    """The true counts stay on the node, so a view can say "9 outputs, 3 drawn"."""
    provider = _provider(
        btc_transaction(
            "whale",
            [out(index, f"addr{index}", 1) for index in range(9)],
            [inp(0, ALICE, 9)],
            block_height=1,
        )
    )
    graph = await _walk(provider, policy=LedgerPolicy(max_depth=1, max_fan_out=3))

    node = graph.node(transaction_node_key(Chain.BITCOIN, "whale"))
    assert isinstance(node, LedgerTransactionNode)
    assert node.n_outputs == 9, "the true count is what lets the view say what is missing"
    assert node.is_collapsed
    assert len(graph.outgoing(node.key)) == 3
    assert graph.stop_reasons.get(POLICY_MAX_FAN_OUT, 0) >= 1


@pytest.mark.anyio
async def test_a_seed_transaction_is_exempt_from_the_value_floor() -> None:
    """The Verify entry: a claim's own transaction can sit outside a dust-bounded walk.

    A derivation whose references point at nodes that are not in the graph is worse than
    no derivation at all.
    """
    provider = _provider(
        btc_transaction("dust", [out(0, BOB, 5)], [inp(0, ALICE, 5)], block_height=1)
    )
    graph = await walk_ledger(
        provider,
        seed_txids=("dust",),
        policy=LedgerPolicy(max_depth=1, min_value=10_000),
    )

    assert graph.transaction_count == 1
    assert {edge.amount for edge in graph.edges} == {5}


@pytest.mark.anyio
async def test_a_seed_transaction_that_does_not_exist_is_reported() -> None:
    graph = await walk_ledger(_provider(), seed_txids=("nope",))
    assert graph.is_empty
    assert any("no transaction" in warning for warning in graph.warnings)


# --------------------------------------------------------------------------- #
# The contract's own promises
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_the_same_seed_walked_twice_gives_the_same_graph() -> None:
    """Reproducibility, excluding the two fields that are *about* when it ran.

    ``generated_at`` and ``elapsed_seconds`` differ by definition; everything that says
    what the chain looks like must not.
    """
    first = await _walk(_linear(), policy=LedgerPolicy(max_depth=2))
    second = await _walk(_linear(), policy=LedgerPolicy(max_depth=2))
    volatile = {"generated_at", "elapsed_seconds"}

    assert first.model_dump(exclude=volatile) == second.model_dump(exclude=volatile)
    assert first.model_dump_json(exclude=volatile) == second.model_dump_json(exclude=volatile)


@pytest.mark.anyio
async def test_the_document_describes_the_walk_that_produced_it() -> None:
    policy = LedgerPolicy(max_depth=1, min_value=10_000)
    graph = await _walk(_linear(), policy=policy, direction=Direction.IN)

    assert graph.policy == policy
    assert graph.direction is Direction.IN
    assert graph.provider == "in-memory"
    assert graph.redistributable, "the in-memory provider's data is ours, so it says so"
    assert graph.schema_version == 1


@pytest.mark.anyio
async def test_the_document_round_trips_through_json() -> None:
    from chainlens.models.ledger import LedgerGraph

    graph = await _walk(_linear(), policy=LedgerPolicy(max_depth=2))
    revived = LedgerGraph.model_validate_json(graph.model_dump_json())
    assert revived.nodes == graph.nodes
    assert revived.edges == graph.edges


@pytest.mark.anyio
async def test_the_addresses_an_address_node_counts_are_the_ones_it_was_in() -> None:
    graph = await _walk(_linear(), policy=LedgerPolicy(max_depth=2))
    alice = graph.node(address_node_key(Chain.BITCOIN, ALICE))
    assert isinstance(alice, LedgerAddressNode)
    assert alice.tx_count == 1
    assert alice.is_seed


@pytest.mark.anyio
async def test_the_assets_seen_are_listed_for_a_front_end_to_label_by() -> None:
    graph = await _walk(_linear(), policy=LedgerPolicy(max_depth=1))
    assert len(graph.assets) == 1
    assert graph.assets[0].chain is Chain.BITCOIN


# --------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_a_walk_needs_something_to_start_from() -> None:
    with pytest.raises(ValueError, match="seed address, a seed transaction, or both"):
        await walk_ledger(_provider())


class _NoHistoryProvider(InMemoryProvider):
    capabilities = frozenset({Capability.ADDRESS, Capability.BALANCE})


@pytest.mark.anyio
async def test_a_provider_that_cannot_list_address_transactions_is_refused() -> None:
    with pytest.raises(CapabilityError):
        await walk_ledger(_NoHistoryProvider(chain=Chain.BITCOIN), seed_address=ALICE)


@pytest.mark.anyio
async def test_an_address_with_no_history_is_a_warning_not_a_failure() -> None:
    provider = _provider(
        btc_transaction("tx1", [out(0, BOB, 60)], [inp(0, ALICE, 60)], block_height=1)
    )
    graph = await _walk(provider, seed="nobody", policy=LedgerPolicy(max_depth=1))

    assert graph.node_count == 1, "the seed is admitted even with nothing to show"
    assert any("no history" in warning for warning in graph.warnings)
