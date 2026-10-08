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
from chainlens.models.flows import ValueFlow
from chainlens.models.primitives import Amount

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
    """A node and what moved through it, in one asset's base units.

    **The amount is tagged**, so a reader of "where does value concentrate" can tell a node whose
    total is entirely recorded from one whose total includes a share this library inferred. See
    :func:`value_by_node`.
    """

    node_key: str
    label: str
    amount: Amount


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


def value_by_node(indexed: IndexedGraph, *, incoming: bool = True) -> Mapping[str, Amount]:
    """Total value per node over the edges arriving at it (or leaving it), **as a tagged amount**.

    **The total used to be a bare `int`, and it discarded a fact the edges were carrying.** Measured
    before this changed: a node receiving 300 recorded plus 100 apportioned reported ``400``, with
    no sign that a quarter of it was this library's inference from a co-funded input — while the
    edges said ``apportioned = [False, True]`` all along. This module's own docstring makes exactly
    that argument for *assets* ("summing edge amounts across a graph that mixes BTC and an ERC-20
    ... produces a number that means nothing") and did not make it for tags.

    So the total is an :class:`~chainlens.models.primitives.Amount`, and `Amount.__add__` carries
    the **weakest** term's tag: a total whose components include an inference is an inference. That
    is the type `chainlens.models.primitives.Amount` was added for, and this is the function it was
    added for — it was otherwise a type with tests and no callers.

    **A node with no edges is absent from the mapping rather than present as zero.** An amount is an
    amount *of* something, and a node nothing moved through names no asset; a `0` would have to
    pick one. Callers that want every node key can read ``indexed.keys()`` and default.

    Scoped to one graph, so it is only meaningful when the graph holds a single asset — and now
    that is enforced rather than asked for: a graph mixing assets raises a `TypeError` from the
    addition instead of returning a sum of two different units. The docstring used to say callers
    "should partition first", which is a rule nothing checked.
    """
    totals: dict[str, Amount] = {}
    for edge in indexed.graph.edge_list():
        source_position, target_position = edge
        flow: ValueFlow = indexed.graph.get_edge_data(source_position, target_position)
        key = indexed.key_of(target_position if incoming else source_position)
        carried = Amount.of_flow(flow)
        totals[key] = totals[key] + carried if key in totals else carried
    return totals


def top_by_value(
    indexed: IndexedGraph, *, incoming: bool = True, limit: int = 10
) -> tuple[NodeValue, ...]:
    """The nodes moving the most value, highest first."""
    totals = value_by_node(indexed, incoming=incoming)
    ranked = sorted(totals.items(), key=lambda item: (-item[1].base_units, item[0]))[:limit]
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
