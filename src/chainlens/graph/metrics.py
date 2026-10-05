"""Graph metrics: what shape is this flow graph, and where does it concentrate.

Everything here is asset-agnostic on purpose. Summing edge amounts across a graph
that mixes BTC and an ERC-20 adds different units together and produces a number
that means nothing, so structural metrics live here and per-asset value
aggregation is a separate, explicitly-scoped function.

Two of these answer the questions an investigation actually starts with:

* **Where does value concentrate?** A handful of high-degree nodes in a trace is
  usually a service, and knowing that early saves expanding a hairball.
* **Is there a cycle?** A round trip between addresses is worth a look, and on a
  trace it is also the thing most likely to send a naive traversal into an
  infinite loop. The tracer records the edges; this finds the loops.
"""

from __future__ import annotations

from collections.abc import Mapping

import rustworkx as rx
from pydantic import Field

from chainlens.graph.build import IndexedGraph
from chainlens.models.base import LensModel

__all__ = [
    "Degree",
    "GraphSummary",
    "NodeValue",
    "betweenness",
    "cycles",
    "cyclic_nodes",
    "degree_table",
    "density",
    "strongly_connected_components",
    "summary",
    "top_by_value",
    "value_by_node",
]

#: Cycles are enumerated up to this many, because a dense graph can contain
#: exponentially many and an investigator wants the first few, not all of them.
_DEFAULT_CYCLE_LIMIT = 100


class Degree(LensModel):
    """How connected one node is.

    Attributes:
        node_key: the node this describes.
        in_degree: distinct sources that sent to it.
        out_degree: distinct destinations it sent to.
    """

    node_key: str
    in_degree: int
    out_degree: int

    @property
    def total(self) -> int:
        return self.in_degree + self.out_degree


class NodeValue(LensModel):
    """A node and an amount, in one asset's base units."""

    node_key: str
    label: str
    amount: int


class GraphSummary(LensModel):
    """A structural description of a flow graph, with no units attached.

    Attributes:
        node_count: nodes in the graph.
        edge_count: edges in the graph.
        density: edges over the maximum possible for this node count, 0.0 when
            there is only one node.
        recurring_node_count: nodes lying on at least one cycle.
        cycle_count: distinct cycles found, up to the enumeration limit.
        max_in_degree: the most sources any single node has.
        max_out_degree: the most destinations any single node has.
        is_cyclic: whether any cycle exists at all.
    """

    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    density: float = Field(ge=0.0, le=1.0)
    recurring_node_count: int = Field(ge=0)
    cycle_count: int = Field(ge=0)
    max_in_degree: int = Field(ge=0)
    max_out_degree: int = Field(ge=0)

    @property
    def is_cyclic(self) -> bool:
        return self.recurring_node_count > 0

    @property
    def mean_out_degree(self) -> float:
        return self.edge_count / self.node_count if self.node_count else 0.0


def density(indexed: IndexedGraph) -> float:
    """Edge count over the maximum possible, for a directed graph without self-loops."""
    count = indexed.node_count
    if count < 2:
        return 0.0
    return indexed.edge_count / (count * (count - 1))


def degree_table(indexed: IndexedGraph) -> Mapping[str, Degree]:
    """Per-node in and out degree, keyed by node key."""
    return {
        key: Degree(
            node_key=key,
            in_degree=indexed.in_degree(key),
            out_degree=indexed.out_degree(key),
        )
        for key in indexed
    }


def strongly_connected_components(indexed: IndexedGraph) -> tuple[tuple[str, ...], ...]:
    """Components of more than one node -- that is, nodes that can reach each other.

    A component of one is just a node, so it is not reported: the question this
    answers is "which nodes are in a loop", and a lone node is not.
    """
    components = rx.strongly_connected_components(indexed.graph)
    return tuple(
        tuple(indexed.key_of(position) for position in component)
        for component in components
        if len(component) > 1
    )


def cyclic_nodes(indexed: IndexedGraph) -> set[str]:
    """Every node lying on a cycle."""
    return {key for component in strongly_connected_components(indexed) for key in component}


def cycles(
    indexed: IndexedGraph, *, limit: int = _DEFAULT_CYCLE_LIMIT
) -> tuple[tuple[str, ...], ...]:
    """Simple cycles as node keys, up to ``limit`` of them.

    Bounded deliberately: the number of simple cycles in a dense graph grows
    exponentially, and a caller wanting to look at round trips wants the first few
    rather than a graph that never returns.
    """
    found: list[tuple[str, ...]] = []
    for cycle in rx.simple_cycles(indexed.graph):
        found.append(tuple(indexed.key_of(position) for position in cycle))
        if len(found) >= limit:
            break
    return tuple(found)


def betweenness(indexed: IndexedGraph) -> Mapping[str, float]:
    """Betweenness centrality per node, normalised.

    High betweenness marks a node that many paths pass through -- typically a
    service, and a place a trace should stop rather than expand.
    """
    centrality = rx.betweenness_centrality(indexed.graph, normalized=True)
    return {indexed.key_of(position): float(value) for position, value in centrality.items()}


def value_by_node(indexed: IndexedGraph, *, incoming: bool = True) -> Mapping[str, int]:
    """Total value per node over the edges arriving at it (or leaving it).

    Scoped to one graph, so it is only meaningful when the graph holds a single
    asset; callers with a mixed graph should partition first.
    """
    totals: dict[str, int] = dict.fromkeys(indexed, 0)
    for edge in indexed.graph.edge_list():
        source_position, target_position = edge
        payload = indexed.graph.get_edge_data(source_position, target_position)
        amount = getattr(payload, "amount", 0)
        key = indexed.key_of(target_position if incoming else source_position)
        totals[key] = totals.get(key, 0) + int(amount)
    return totals


def top_by_value(
    indexed: IndexedGraph, *, incoming: bool = True, limit: int = 10
) -> tuple[NodeValue, ...]:
    """The nodes moving the most value, highest first."""
    totals = value_by_node(indexed, incoming=incoming)
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return tuple(
        NodeValue(node_key=key, label=_node_label(indexed, key), amount=amount)
        for key, amount in ranked
    )


def _node_label(indexed: IndexedGraph, node_key: str) -> str:
    position = indexed.index_of(node_key)
    return "" if position is None else str(indexed.node_at(position))


def summary(indexed: IndexedGraph, *, cycle_limit: int = _DEFAULT_CYCLE_LIMIT) -> GraphSummary:
    """Structural summary of a flow graph."""
    degrees = degree_table(indexed)
    return GraphSummary(
        node_count=indexed.node_count,
        edge_count=indexed.edge_count,
        density=round(density(indexed), 6),
        recurring_node_count=len(cyclic_nodes(indexed)),
        cycle_count=len(cycles(indexed, limit=cycle_limit)),
        max_in_degree=max((degree.in_degree for degree in degrees.values()), default=0),
        max_out_degree=max((degree.out_degree for degree in degrees.values()), default=0),
    )
