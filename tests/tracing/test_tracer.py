"""Tracer tests: bounded walks, pruning, stop rules and clustering composition.

Every fixture here is an ``InMemoryProvider``, so the whole tracing layer is
exercised with no network and no cassettes.
"""

from __future__ import annotations

import pytest

from chainlens.analysis.clustering import Clusterer
from chainlens.analysis.heuristics.common_input import CommonInputOwnership
from chainlens.exceptions import CapabilityError
from chainlens.models.entities import Evidence, Label, Merge
from chainlens.models.enums import Direction, EntityKind, LabelSource
from chainlens.models.flows import AddressRef, EntityRef, FlowGraph, NodeRef
from chainlens.providers.capabilities import Capability
from chainlens.testing import InMemoryProvider
from chainlens.testing.factories import btc_transaction, inp, make_provenance, out
from chainlens.tracing import (
    BUDGET_DEPTH,
    BUDGET_EDGES,
    BUDGET_NODES,
    POLICY_MAX_FAN_OUT,
    PruningPolicy,
    StopRule,
    TraceBudget,
    Tracer,
    TraversalStrategy,
)

ALICE, BOB, CAROL, DAVE = "alice", "bob", "carol", "dave"
HUNDRED = 100_000_000


def _linear() -> InMemoryProvider:
    """alice -> bob -> carol -> dave, one transaction each."""
    return InMemoryProvider(
        transactions=[
            btc_transaction(
                "tx1", [out(0, BOB, HUNDRED)], [inp(0, ALICE, HUNDRED)], block_height=1
            ),
            btc_transaction(
                "tx2", [out(0, CAROL, HUNDRED)], [inp(0, BOB, HUNDRED)], block_height=2
            ),
            btc_transaction(
                "tx3", [out(0, DAVE, HUNDRED)], [inp(0, CAROL, HUNDRED)], block_height=3
            ),
        ]
    )


def _label_of(node: NodeRef) -> str:
    """An address, or a stand-in for an entity node."""
    return node.address if isinstance(node, AddressRef) else f"<entity:{node.entity_id}>"


def _keys(graph: FlowGraph) -> list[tuple[str, str]]:
    """Every edge as ``(src, dst)`` labels, entities included."""
    return [(_label_of(edge.src), _label_of(edge.dst)) for edge in graph.edges]


def _outgoing_labels(graph: FlowGraph) -> set[str]:
    return {dst for _, dst in _keys(graph)}


class _NoHistory(InMemoryProvider):
    capabilities = frozenset({Capability.ADDRESS, Capability.BALANCE})


# --------------------------------------------------------------------------- #
# The basic walk
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_a_linear_chain_is_walked() -> None:
    graph = await Tracer(_linear()).trace(ALICE, budget=TraceBudget(max_depth=5))
    assert _keys(graph) == [(ALICE, BOB), (BOB, CAROL), (CAROL, DAVE)]
    assert graph.depth_reached == 3
    assert not graph.truncated


@pytest.mark.anyio
async def test_edges_carry_the_evidence_to_re_derive_them() -> None:
    """An edge a reader cannot check is just a picture."""
    provenance = make_provenance(provider="mempool", request_id="req-1")
    provider = InMemoryProvider(
        transactions=[
            btc_transaction(
                "tx1",
                [out(0, BOB, HUNDRED)],
                [inp(0, ALICE, HUNDRED)],
                block_height=1,
                provenance=provenance,
            )
        ]
    )
    graph = await Tracer(provider).trace(ALICE, budget=TraceBudget(max_depth=5))
    edge = graph.edges[0]
    assert edge.txids == ("tx1",)
    assert edge.n_transfers == 1
    assert edge.provenance is not None
    assert edge.provenance.request_id == "req-1"


@pytest.mark.anyio
async def test_paths_run_from_the_seed() -> None:
    graph = await Tracer(_linear()).trace(ALICE, budget=TraceBudget(max_depth=5))
    last = graph.edges[-1]
    assert last.path == tuple(f"address:{graph.chain}:{name}" for name in (ALICE, BOB, CAROL, DAVE))


@pytest.mark.anyio
async def test_tracing_inward_walks_backwards() -> None:
    graph = await Tracer(_linear()).trace(
        DAVE, direction=Direction.IN, budget=TraceBudget(max_depth=5)
    )
    # Edges stay oriented by the real movement; the walk just goes the other way.
    assert _keys(graph) == [(ALICE, BOB), (BOB, CAROL), (CAROL, DAVE)]


@pytest.mark.anyio
async def test_tracing_in_both_directions_from_the_middle() -> None:
    graph = await Tracer(_linear()).trace(
        CAROL, direction=Direction.BOTH, budget=TraceBudget(max_depth=5)
    )
    assert set(_keys(graph)) == {(ALICE, BOB), (BOB, CAROL), (CAROL, DAVE)}


@pytest.mark.anyio
async def test_repeated_transfers_between_the_same_pair_are_aggregated() -> None:
    provider = InMemoryProvider(
        transactions=[
            btc_transaction("tx1", [out(0, BOB, 10_000_000)], [inp(0, ALICE, 10_000_000)]),
            btc_transaction("tx2", [out(0, BOB, 20_000_000)], [inp(0, ALICE, 20_000_000)]),
        ]
    )
    graph = await Tracer(provider).trace(ALICE, budget=TraceBudget(max_depth=5))
    assert graph.edge_count == 1
    edge = graph.edges[0]
    assert edge.amount == 30_000_000
    assert edge.n_transfers == 2
    assert set(edge.txids) == {"tx1", "tx2"}


@pytest.mark.anyio
async def test_depth_first_visits_the_same_graph() -> None:
    breadth = await Tracer(_linear()).trace(ALICE, budget=TraceBudget(max_depth=5))
    depth = await Tracer(_linear()).trace(
        ALICE, strategy=TraversalStrategy.DEPTH_FIRST, budget=TraceBudget(max_depth=5)
    )
    assert set(_keys(breadth)) == set(_keys(depth))


@pytest.mark.anyio
async def test_the_same_input_gives_the_same_graph() -> None:
    """Reproducibility: a report built from a trace must be re-derivable."""
    first = await Tracer(_linear()).trace(ALICE, budget=TraceBudget(max_depth=5))
    second = await Tracer(_linear()).trace(ALICE, budget=TraceBudget(max_depth=5))
    assert first.edges == second.edges
    assert first.nodes == second.nodes


@pytest.mark.anyio
async def test_one_tracer_can_walk_twice_without_leaking_state() -> None:
    tracer = Tracer(_linear())
    first = await tracer.trace(ALICE, budget=TraceBudget(max_depth=5))
    second = await tracer.trace(ALICE, budget=TraceBudget(max_depth=2))
    assert first.depth_reached == 3
    assert second.depth_reached == 2


# --------------------------------------------------------------------------- #
# Budgets, and reporting when they bite
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_a_depth_limit_is_reported_as_truncation() -> None:
    """A short graph because we stopped looking must not look genuinely short."""
    graph = await Tracer(_linear()).trace(ALICE, budget=TraceBudget(max_depth=2))
    assert graph.edge_count == 2
    assert graph.truncated
    assert graph.stop_reasons[BUDGET_DEPTH] >= 1


@pytest.mark.anyio
async def test_a_node_budget_is_reported() -> None:
    graph = await Tracer(_linear()).trace(ALICE, budget=TraceBudget(max_depth=5, max_nodes=2))
    assert graph.truncated
    assert graph.stop_reasons.get(BUDGET_NODES, 0) >= 1
    assert graph.node_count == 2


@pytest.mark.anyio
async def test_an_edge_budget_is_reported() -> None:
    graph = await Tracer(_linear()).trace(ALICE, budget=TraceBudget(max_depth=5, max_edges=1))
    assert graph.edge_count == 1
    assert graph.truncated
    assert graph.stop_reasons.get(BUDGET_EDGES, 0) >= 1


@pytest.mark.anyio
async def test_a_zero_time_budget_stops_immediately_and_says_so() -> None:
    graph = await Tracer(_linear()).trace(
        ALICE, budget=TraceBudget(max_depth=5, time_budget=0.0001)
    )
    assert graph.is_empty or graph.truncated


# --------------------------------------------------------------------------- #
# Pruning
# --------------------------------------------------------------------------- #
def _with_dust() -> InMemoryProvider:
    return InMemoryProvider(
        transactions=[
            btc_transaction(
                "tx1",
                [out(0, BOB, HUNDRED), out(1, "dustbin", 546)],
                [inp(0, ALICE, HUNDRED + 546)],
                block_height=1,
            )
        ]
    )


@pytest.mark.anyio
async def test_a_minimum_value_drops_dust() -> None:
    graph = await Tracer(_with_dust()).trace(
        ALICE, policy=PruningPolicy(min_value=1_000), budget=TraceBudget(max_depth=5)
    )
    assert _keys(graph) == [(ALICE, BOB)]


@pytest.mark.anyio
async def test_without_a_minimum_value_dust_is_followed() -> None:
    graph = await Tracer(_with_dust()).trace(ALICE, budget=TraceBudget(max_depth=5))
    assert "dustbin" in _outgoing_labels(graph)


@pytest.mark.anyio
async def test_a_maximum_value_drops_whale_movements() -> None:
    """A consolidated transfer is not evidence of a relationship between two actors."""
    graph = await Tracer(_with_dust()).trace(
        ALICE, policy=PruningPolicy(max_value=1_000), budget=TraceBudget(max_depth=5)
    )
    # The 1 BTC output is over the cap and gone; the 546-sat output survives it.
    assert _keys(graph) == [(ALICE, "dustbin")]


@pytest.mark.anyio
async def test_a_dust_ratio_drops_small_outputs_of_large_transactions() -> None:
    graph = await Tracer(_with_dust()).trace(
        ALICE, policy=PruningPolicy(dust_ratio=0.01), budget=TraceBudget(max_depth=5)
    )
    assert _keys(graph) == [(ALICE, BOB)]


@pytest.mark.anyio
async def test_max_fan_out_drops_a_service_shaped_expansion() -> None:
    """A node paying many addresses is a service; keeping some of it is arbitrary."""
    provider = InMemoryProvider(
        transactions=[
            btc_transaction(
                "tx1",
                [out(index, f"recipient{index}", 1000) for index in range(5)],
                [inp(0, ALICE, 5000)],
            )
        ]
    )
    graph = await Tracer(provider).trace(
        ALICE, policy=PruningPolicy(max_fan_out=3), budget=TraceBudget(max_depth=5)
    )
    assert graph.is_empty
    assert graph.stop_reasons[POLICY_MAX_FAN_OUT] == 1


@pytest.mark.anyio
async def test_a_self_transfer_is_dropped_by_default() -> None:
    """Change coming back to the sender is not a payment."""
    provider = InMemoryProvider(
        transactions=[
            btc_transaction("tx1", [out(0, ALICE, HUNDRED)], [inp(0, ALICE, HUNDRED + 1)])
        ]
    )
    graph = await Tracer(provider).trace(ALICE, budget=TraceBudget(max_depth=5))
    assert graph.is_empty


@pytest.mark.anyio
async def test_a_coinbase_produces_no_edge() -> None:
    """Minted value has no sender, and the tracer does not invent one.

    Not drawable at all, not merely skipped: a ``FlowGraph`` node is an address or a
    cluster of addresses, and a coinbase has no address to come from. Naming a miner
    would be a fabrication, which is why the coinbase branch in ``_utxo_transfers``
    leaves ``src`` as None — and why there is no node to attach the edge to.
    """
    provider = InMemoryProvider(
        transactions=[btc_transaction("cb", [out(0, ALICE, HUNDRED)], is_coinbase=True)]
    )
    graph = await Tracer(provider).trace(ALICE, budget=TraceBudget(max_depth=5))
    assert graph.is_empty


@pytest.mark.anyio
async def test_a_kept_coinbase_is_reported_as_undrawable_rather_than_dropped() -> None:
    """``skip_coinbase=False`` says what it cannot do instead of silently doing nothing.

    Regression: ``_keep`` rejected any transfer with ``src is None`` *before* it
    consulted ``skip_coinbase``, so the flag was dead configuration with no way to
    observe that. It is still not drawable — there is no node kind for minted value —
    but the trace now says so, once, rather than leaving a reader to conclude the
    setting works.
    """
    provider = InMemoryProvider(
        transactions=[
            btc_transaction("cb", [out(0, ALICE, HUNDRED)], is_coinbase=True),
            btc_transaction("cb2", [out(0, ALICE, HUNDRED)], is_coinbase=True),
        ]
    )
    graph = await Tracer(provider).trace(
        ALICE,
        direction=Direction.IN,
        policy=PruningPolicy(skip_coinbase=False),
        budget=TraceBudget(max_depth=5),
    )

    assert graph.is_empty
    undrawable = [warning for warning in graph.warnings if "minted value" in warning]
    assert len(undrawable) == 1, "reported once per trace, not once per block reward"


@pytest.mark.anyio
async def test_the_default_policy_says_nothing_about_coinbase() -> None:
    """The warning is for a policy that asked for something, not for the default."""
    provider = InMemoryProvider(
        transactions=[btc_transaction("cb", [out(0, ALICE, HUNDRED)], is_coinbase=True)]
    )
    graph = await Tracer(provider).trace(
        ALICE, direction=Direction.IN, budget=TraceBudget(max_depth=5)
    )
    assert graph.is_empty
    assert not any("minted value" in warning for warning in graph.warnings)


# --------------------------------------------------------------------------- #
# Stop rules
# --------------------------------------------------------------------------- #
def _labelled(kind: EntityKind) -> dict[str, tuple[Label, ...]]:
    return {
        BOB: (
            Label(
                name="Somewhere",
                source=LabelSource.PROVIDER,
                kind=kind,
                address=BOB,
            ),
        )
    }


@pytest.mark.anyio
async def test_a_labelled_node_is_not_expanded_under_the_label_rule() -> None:
    graph = await Tracer(_linear(), labels=_labelled(EntityKind.UNKNOWN)).trace(
        ALICE, stop_at=frozenset({StopRule.LABELED}), budget=TraceBudget(max_depth=5)
    )
    assert _keys(graph) == [(ALICE, BOB)]  # the edge is recorded, the node is not walked
    assert graph.stop_reasons[StopRule.LABELED.value] == 1


@pytest.mark.anyio
async def test_the_service_rule_only_stops_at_services() -> None:
    """An unlabelled-kind label stops the LABELED rule but not KNOWN_SERVICE."""
    unknown = await Tracer(_linear(), labels=_labelled(EntityKind.UNKNOWN)).trace(
        ALICE, stop_at=frozenset({StopRule.KNOWN_SERVICE}), budget=TraceBudget(max_depth=5)
    )
    assert len(unknown.edges) == 3  # walked straight through

    exchange = await Tracer(_linear(), labels=_labelled(EntityKind.EXCHANGE)).trace(
        ALICE, stop_at=frozenset({StopRule.KNOWN_SERVICE}), budget=TraceBudget(max_depth=5)
    )
    assert _keys(exchange) == [(ALICE, BOB)]
    assert exchange.stop_reasons[StopRule.KNOWN_SERVICE.value] == 1


@pytest.mark.anyio
async def test_without_stop_rules_a_labelled_node_is_expanded() -> None:
    graph = await Tracer(_linear(), labels=_labelled(EntityKind.EXCHANGE)).trace(
        ALICE, budget=TraceBudget(max_depth=5)
    )
    assert len(graph.edges) == 3


# --------------------------------------------------------------------------- #
# Clustering composition
# --------------------------------------------------------------------------- #
def _merged_clusterer(*addresses: str) -> Clusterer:
    merger = Clusterer()
    merger.apply_merge(
        Merge(
            addresses=frozenset(addresses),
            confidence=0.9,
            evidence=Evidence(heuristic=CommonInputOwnership.name, confidence=0.9),
        )
    )
    return merger


@pytest.mark.anyio
async def test_a_cluster_turns_an_address_graph_into_an_entity_graph() -> None:
    """The point of composing the two layers."""
    clusterer = _merged_clusterer(ALICE, BOB)
    graph = await Tracer(_linear(), clusterer=clusterer).trace(
        ALICE, budget=TraceBudget(max_depth=5)
    )
    assert isinstance(graph.seed, EntityRef)
    assert graph.seed.entity_id == clusterer.cluster_id(frozenset({ALICE, BOB}))

    keys = _keys(graph)
    # The entity's outward edge, and the next hop, both survive.
    assert (f"<entity:{graph.seed.entity_id}>", CAROL) in keys
    assert (CAROL, DAVE) in keys
    # alice -> bob is internal to the entity now, so it is a self-loop and dropped.
    assert (ALICE, BOB) not in keys


@pytest.mark.anyio
async def test_cluster_boundary_stops_expansion_outside_the_seed_entity() -> None:
    clusterer = _merged_clusterer(ALICE, BOB)
    graph = await Tracer(_linear(), clusterer=clusterer).trace(
        ALICE,
        stop_at=frozenset({StopRule.CLUSTER_BOUNDARY}),
        budget=TraceBudget(max_depth=5),
    )
    # The entity's edge outward is recorded, but carol is never walked, so the
    # next hop is absent. Recording the edge and refusing to follow it is the
    # whole point of the rule.
    assert isinstance(graph.seed, EntityRef)
    keys = _keys(graph)
    assert (_label_of(graph.seed), CAROL) in keys
    assert (CAROL, DAVE) not in keys
    assert graph.stop_reasons[StopRule.CLUSTER_BOUNDARY.value] >= 1


@pytest.mark.anyio
async def test_an_entity_node_takes_its_label_from_a_member() -> None:
    clusterer = _merged_clusterer(ALICE, BOB)
    labels = {
        BOB: (
            Label(
                name="Binance",
                source=LabelSource.PROVIDER,
                kind=EntityKind.EXCHANGE,
                address=BOB,
            ),
        )
    }
    graph = await Tracer(_linear(), clusterer=clusterer, labels=labels).trace(
        ALICE, budget=TraceBudget(max_depth=5)
    )
    assert isinstance(graph.seed, EntityRef)
    assert graph.seed.label == "Binance"


# --------------------------------------------------------------------------- #
# Capability requirement and edge cases
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_tracing_requires_address_history() -> None:
    with pytest.raises(CapabilityError) as caught:
        await Tracer(_NoHistory()).trace(ALICE)
    assert caught.value.capability == Capability.ADDRESS_TXS.value


@pytest.mark.anyio
async def test_an_address_with_no_history_yields_an_empty_graph() -> None:
    graph = await Tracer(_linear()).trace("nobody", budget=TraceBudget(max_depth=5))
    assert graph.is_empty
    assert graph.node_count == 1


@pytest.mark.anyio
async def test_an_ambiguous_transfer_lowers_the_edge_confidence() -> None:
    """An apportioned split is an inference, and the edge says so."""
    provider = InMemoryProvider(
        transactions=[
            btc_transaction(
                "tx1",
                [out(0, BOB, HUNDRED)],
                [inp(0, ALICE, 60_000_000), inp(1, CAROL, 40_000_000)],
            )
        ]
    )
    graph = await Tracer(provider).trace(ALICE, budget=TraceBudget(max_depth=5))
    assert graph.edges
    assert all(edge.confidence < 1.0 for edge in graph.edges)


@pytest.mark.anyio
async def test_a_direct_transfer_keeps_full_confidence() -> None:
    graph = await Tracer(_linear()).trace(ALICE, budget=TraceBudget(max_depth=5))
    assert all(edge.confidence == 1.0 for edge in graph.edges)


@pytest.mark.anyio
async def test_graph_assets_are_reported() -> None:
    graph = await Tracer(_linear()).trace(ALICE, budget=TraceBudget(max_depth=5))
    assets = graph.assets()
    assert len(assets) == 1
    assert assets[0].is_native
