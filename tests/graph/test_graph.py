"""Graph building, metrics and serialisation."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from chainlens.graph import (
    betweenness,
    cycles,
    cyclic_nodes,
    degree_table,
    density,
    strongly_connected_components,
    summary,
    to_cytoscape_json,
    to_dot,
    to_graphml,
    to_mermaid,
    to_rustworkx,
    top_by_value,
    value_by_node,
)
from chainlens.models.enums import AssetKind, Chain
from chainlens.models.flows import AddressRef, EntityRef, FlowGraph, ValueFlow
from chainlens.models.primitives import AssetRef

ALICE, BOB, CAROL, DAVE = "alice", "bob", "carol", "dave"


def _ref(address: str) -> AddressRef:
    return AddressRef(chain=Chain.BITCOIN, address=address)


def _edge(src: str, dst: str, amount: int) -> ValueFlow:
    return ValueFlow(
        chain=Chain.BITCOIN,
        src=_ref(src),
        dst=_ref(dst),
        asset=AssetRef.native(Chain.BITCOIN, symbol="BTC", decimals=8),
        amount=amount,
        txids=(f"tx-{src}-{dst}",),
        path=(f"address:{Chain.BITCOIN}:{src}", f"address:{Chain.BITCOIN}:{dst}"),
    )


def _chain_graph() -> FlowGraph:
    """alice -> bob -> carol, no cycles."""
    return FlowGraph(
        chain=Chain.BITCOIN,
        seed=_ref(ALICE),
        nodes=(_ref(ALICE), _ref(BOB), _ref(CAROL)),
        edges=(_edge(ALICE, BOB, 100), _edge(BOB, CAROL, 60), _edge(ALICE, CAROL, 40)),
    )


def _cyclic_graph() -> FlowGraph:
    """alice -> bob -> carol -> alice."""
    return FlowGraph(
        chain=Chain.BITCOIN,
        seed=_ref(ALICE),
        nodes=(_ref(ALICE), _ref(BOB), _ref(CAROL)),
        edges=(_edge(ALICE, BOB, 100), _edge(BOB, CAROL, 100), _edge(CAROL, ALICE, 100)),
    )


def _key(address: str) -> str:
    return f"address:{Chain.BITCOIN}:{address}"


# --------------------------------------------------------------------------- #
# Building
# --------------------------------------------------------------------------- #
def test_the_digraph_mirrors_the_flow_graph() -> None:
    indexed = to_rustworkx(_chain_graph())
    assert indexed.node_count == 3
    assert indexed.edge_count == 3
    assert set(indexed.keys()) == {_key(name) for name in (ALICE, BOB, CAROL)}


def test_node_and_edge_payloads_are_the_models() -> None:
    indexed = to_rustworkx(_chain_graph())
    position = indexed.index_of(_key(ALICE))
    assert position is not None
    assert indexed.node_at(position) == _ref(ALICE)

    payload = indexed.edge_payload(_key(ALICE), _key(BOB))
    assert payload is not None
    assert payload.amount == 100
    assert payload.txids == ("tx-alice-bob",)


def test_degrees_are_counted() -> None:
    indexed = to_rustworkx(_chain_graph())
    assert indexed.out_degree(_key(ALICE)) == 2
    assert indexed.in_degree(_key(ALICE)) == 0
    assert indexed.in_degree(_key(CAROL)) == 2


def test_an_unknown_key_has_a_safe_degree_and_no_edge() -> None:
    indexed = to_rustworkx(_chain_graph())
    assert indexed.index_of("nope") is None
    assert indexed.in_degree("nope") == 0
    assert indexed.edge_payload("nope", _key(BOB)) is None


def test_an_edge_endpoint_missing_from_nodes_is_added_not_dropped() -> None:
    """Silently discarding an edge would change the answer."""
    graph = FlowGraph(
        chain=Chain.BITCOIN,
        seed=_ref(ALICE),
        nodes=(_ref(ALICE),),
        edges=(_edge(ALICE, DAVE, 10),),
    )
    indexed = to_rustworkx(graph)
    assert indexed.node_count == 2
    assert indexed.edge_count == 1


def test_an_empty_graph_builds() -> None:
    indexed = to_rustworkx(FlowGraph(chain=Chain.BITCOIN, seed=_ref(ALICE)))
    assert indexed.node_count == 0
    assert indexed.edge_count == 0


def test_entity_nodes_are_preserved() -> None:
    entity = EntityRef(chain=Chain.BITCOIN, entity_id="e1", label="Binance")
    graph = FlowGraph(
        chain=Chain.BITCOIN,
        seed=entity,
        nodes=(entity, _ref(BOB)),
        edges=(
            ValueFlow(
                chain=Chain.BITCOIN,
                src=entity,
                dst=_ref(BOB),
                asset=AssetRef.native(Chain.BITCOIN),
                amount=5,
            ),
        ),
    )
    indexed = to_rustworkx(graph)
    assert indexed.node_at(indexed.index_of("entity:bitcoin:e1") or 0) == entity


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def test_density() -> None:
    indexed = to_rustworkx(_chain_graph())
    # 3 edges of a possible 3 * 2 = 6
    assert density(indexed) == pytest.approx(0.5)


def test_density_of_a_single_node_is_zero() -> None:
    indexed = to_rustworkx(FlowGraph(chain=Chain.BITCOIN, seed=_ref(ALICE)))
    assert density(indexed) == 0.0


def test_a_chain_has_no_cycles() -> None:
    indexed = to_rustworkx(_chain_graph())
    assert strongly_connected_components(indexed) == ()
    assert cyclic_nodes(indexed) == set()
    assert cycles(indexed) == ()
    assert not summary(indexed).is_cyclic


def test_a_round_trip_is_detected() -> None:
    indexed = to_rustworkx(_cyclic_graph())
    components = strongly_connected_components(indexed)
    assert len(components) == 1
    assert set(components[0]) == {_key(name) for name in (ALICE, BOB, CAROL)}
    assert summary(indexed).is_cyclic


def test_cycles_are_enumerated_as_node_keys() -> None:
    indexed = to_rustworkx(_cyclic_graph())
    found = cycles(indexed)
    assert len(found) >= 1
    assert set(found[0]) == {_key(name) for name in (ALICE, BOB, CAROL)}


def test_cycle_enumeration_is_bounded() -> None:
    """A dense graph has exponentially many cycles; the caller wants the first few."""
    graph = _cyclic_graph()
    indexed = to_rustworkx(graph)
    assert len(cycles(indexed, limit=1)) == 1


def test_degree_table_covers_every_node() -> None:
    indexed = to_rustworkx(_chain_graph())
    table = degree_table(indexed)
    assert set(table) == {_key(name) for name in (ALICE, BOB, CAROL)}
    assert table[_key(BOB)].in_degree == 1
    assert table[_key(BOB)].out_degree == 1
    assert table[_key(BOB)].total == 2


def test_betweenness_identifies_the_node_paths_pass_through() -> None:
    """A node only has betweenness if some shortest path must go through it.

    The chain fixture has a direct alice -> carol edge, so bob is bypassable and
    scores zero; this graph removes it, forcing the path through bob.
    """
    graph = FlowGraph(
        chain=Chain.BITCOIN,
        seed=_ref(ALICE),
        nodes=(_ref(ALICE), _ref(BOB), _ref(CAROL)),
        edges=(_edge(ALICE, BOB, 100), _edge(BOB, CAROL, 60)),
    )
    reported = betweenness(to_rustworkx(graph))
    assert reported[_key(BOB)] > 0.0
    assert reported[_key(ALICE)] == 0.0


def test_value_by_node_sums_incoming_and_outgoing() -> None:
    indexed = to_rustworkx(_chain_graph())
    incoming = value_by_node(indexed)
    assert incoming[_key(CAROL)] == 100  # 60 + 40
    outgoing = value_by_node(indexed, incoming=False)
    assert outgoing[_key(ALICE)] == 140  # 100 + 40


def test_top_by_value_is_ranked() -> None:
    indexed = to_rustworkx(_chain_graph())
    top = top_by_value(indexed, incoming=True, limit=2)
    # bob and carol both receive 100; ties break on key, so the order is stable.
    assert [entry.amount for entry in top] == [100, 100]
    assert {entry.node_key for entry in top} == {_key(BOB), _key(CAROL)}
    assert top_by_value(indexed, incoming=True, limit=1)[0].node_key == _key(BOB)


def test_summary_reports_structure_not_units() -> None:
    report = summary(to_rustworkx(_chain_graph()))
    assert report.node_count == 3
    assert report.edge_count == 3
    assert report.max_out_degree == 2
    assert report.max_in_degree == 2
    assert report.cycle_count == 0
    assert report.mean_out_degree == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Serialisation
# --------------------------------------------------------------------------- #
def test_graphml_is_well_formed_and_carries_the_evidence() -> None:
    """A picture of money moving is only useful if a reader can go and check."""
    payload = to_graphml(_chain_graph())
    root = ET.fromstring(payload)
    namespace = {"g": "http://graphml.graphdrawing.org/xmlns"}
    nodes = root.findall(".//g:node", namespace)
    edges = root.findall(".//g:edge", namespace)
    assert len(nodes) == 3
    assert len(edges) == 3
    assert "tx-alice-bob" in payload
    # Amounts go in as integers, so a tool can filter and size by them.
    assert '<data key="e_amount">100</data>' in payload


def test_graphml_escapes_hostile_labels() -> None:
    graph = FlowGraph(
        chain=Chain.BITCOIN,
        seed=_ref("a<b>&c"),
        nodes=(_ref("a<b>&c"),),
        edges=(),
    )
    payload = to_graphml(graph)
    ET.fromstring(payload)  # must parse, not merely be produced
    assert "a&lt;b&gt;&amp;c" in payload


def test_cytoscape_json_is_valid_and_structured() -> None:
    payload = json.loads(to_cytoscape_json(_chain_graph()))
    assert len(payload["elements"]["nodes"]) == 3
    assert len(payload["elements"]["edges"]) == 3
    edge = next(
        item for item in payload["elements"]["edges"] if item["data"]["source"] == _key(ALICE)
    )
    assert edge["data"]["amount"] == 100
    assert edge["data"]["amount_label"] == "0.00000100 BTC"
    assert edge["data"]["txids"]


def test_cytoscape_json_marks_apportioned_edges() -> None:
    edge = _edge(ALICE, BOB, 100).model_copy(update={"apportioned": True})
    graph = FlowGraph(
        chain=Chain.BITCOIN, seed=_ref(ALICE), nodes=(_ref(ALICE), _ref(BOB)), edges=(edge,)
    )
    payload = json.loads(to_cytoscape_json(graph))
    assert payload["elements"]["edges"][0]["data"]["apportioned"] is True


def test_dot_names_every_node_and_edge() -> None:
    payload = to_dot(_chain_graph())
    assert payload.startswith("digraph flows {")
    assert _key(ALICE) in payload
    assert "->" in payload
    assert "0.00000100 BTC" in payload


def test_mermaid_aliases_node_ids_because_keys_contain_colons() -> None:
    payload = to_mermaid(_chain_graph())
    assert payload.startswith("flowchart LR")
    assert "n0[" in payload
    assert "-->" in payload
    # The raw key must not appear as a node identifier -- mermaid parses colons.
    assert f"{_key(ALICE)}[" not in payload


def test_mermaid_states_truncation() -> None:
    """A diagram is the easiest artifact to mistake for a complete one."""
    payload = to_mermaid(_chain_graph(), max_nodes=2)
    assert "truncated" in payload
    assert "showing 2 of 3 nodes" in payload


def test_an_asset_without_decimals_falls_back_to_base_units() -> None:
    """Rendering must not guess decimals to make a label look nicer."""
    token = AssetRef(chain=Chain.ETHEREUM, kind=AssetKind.ERC20, contract="0xdead")
    edge = ValueFlow(
        chain=Chain.ETHEREUM,
        src=AddressRef(chain=Chain.ETHEREUM, address=ALICE),
        dst=AddressRef(chain=Chain.ETHEREUM, address=BOB),
        asset=token,
        amount=1000,
    )
    graph = FlowGraph(
        chain=Chain.ETHEREUM,
        seed=AddressRef(chain=Chain.ETHEREUM, address=ALICE),
        nodes=(edge.src, edge.dst),
        edges=(edge,),
    )
    assert "base units" in to_dot(graph)


def test_every_format_handles_an_empty_graph() -> None:
    empty = FlowGraph(chain=Chain.BITCOIN, seed=_ref(ALICE))
    ET.fromstring(to_graphml(empty))
    assert json.loads(to_cytoscape_json(empty))["elements"] == {"nodes": [], "edges": []}
    assert to_dot(empty).startswith("digraph")
    assert to_mermaid(empty).startswith("flowchart")
