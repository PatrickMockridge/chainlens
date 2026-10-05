"""Build a rustworkx digraph from a :class:`~chainlens.models.flows.FlowGraph`.

The graph engine is deliberately *not* part of the data model. A ``FlowGraph`` is
pure pydantic data that can be serialised, snapshotted and compared; this module
turns it into an indexed digraph for algorithms. That way the backend can be
replaced without touching tracing or reporting, and most tests never need
rustworkx at all.

rustworkx was chosen over networkx because a depth-5 trace off a busy address
routinely reaches six figures of nodes, where networkx's pure-Python traversal
becomes the bottleneck. ``networkx`` remains available through the ``[nx]`` extra
for its ecosystem and layout algorithms.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping

import rustworkx as rx

from chainlens.models.flows import AddressRef, EntityRef, FlowGraph, NodeRef, ValueFlow

__all__ = ["IndexedGraph", "to_rustworkx"]


class IndexedGraph:
    """A rustworkx digraph plus the node-key index it was built with.

    rustworkx addresses nodes by integer position, so every caller needs the
    key-to-position map. Keeping it here, next to the graph it describes, is what
    stops that map from being rebuilt inconsistently -- or off by one -- at each
    call site.
    """

    __slots__ = ("_graph", "_index", "_keys")

    def __init__(self, graph: rx.PyDiGraph, index: Mapping[str, int]) -> None:
        self._graph = graph
        self._index: dict[str, int] = dict(index)
        self._keys: dict[int, str] = {position: key for key, position in self._index.items()}

    @property
    def graph(self) -> rx.PyDiGraph:
        """The underlying digraph. Node and edge payloads are chainlens models."""
        return self._graph

    @property
    def node_count(self) -> int:
        return self._graph.num_nodes()

    @property
    def edge_count(self) -> int:
        return self._graph.num_edges()

    def keys(self) -> tuple[str, ...]:
        """Every node key, in position order."""
        return tuple(self._keys[position] for position in range(len(self._keys)))

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def __len__(self) -> int:
        return self.node_count

    def index_of(self, node_key: str) -> int | None:
        """The digraph position of a node, or ``None`` if it is not present."""
        return self._index.get(node_key)

    def key_of(self, position: int) -> str:
        return self._keys[position]

    def node_at(self, position: int) -> NodeRef:
        """The node payload at a position.

        Validated rather than cast: rustworkx payloads are untyped, so a graph built
        by anything other than :func:`to_rustworkx` could hold something else, and
        failing here with a clear message beats an ``AttributeError`` three layers
        up.
        """
        node = self._graph[position]
        if not isinstance(node, (AddressRef, EntityRef)):
            raise TypeError(
                f"node payload at position {position} is not a NodeRef: {type(node).__name__}"
            )
        return node

    def edge_payload(self, src_key: str, dst_key: str) -> ValueFlow | None:
        """The :class:`ValueFlow` on an edge, or ``None`` if there is no such edge."""
        src = self._index.get(src_key)
        dst = self._index.get(dst_key)
        if src is None or dst is None:
            return None
        payload = self._graph.get_edge_data(src, dst)
        return payload if isinstance(payload, ValueFlow) else None

    def in_degree(self, node_key: str) -> int:
        position = self._index.get(node_key)
        return 0 if position is None else int(self._graph.in_degree(position))

    def out_degree(self, node_key: str) -> int:
        position = self._index.get(node_key)
        return 0 if position is None else int(self._graph.out_degree(position))


def to_rustworkx(flow_graph: FlowGraph) -> IndexedGraph:
    """Build an :class:`IndexedGraph` from a value-flow graph.

    Node payloads are the :data:`~chainlens.models.flows.NodeRef` objects and edge
    payloads are the :class:`ValueFlow` objects, so an algorithm result can be
    traced straight back to the evidence it came from.

    An edge endpoint missing from ``flow_graph.nodes`` is added rather than the
    edge being dropped: silently discarding an edge would change the answer, and a
    quietly incomplete graph is the failure mode this library works hardest to
    avoid.
    """
    graph: rx.PyDiGraph = rx.PyDiGraph()
    index: dict[str, int] = {}

    for node in flow_graph.nodes:
        index[node.node_key] = graph.add_node(node)

    for edge in flow_graph.edges:
        for endpoint in (edge.src, edge.dst):
            if endpoint.node_key not in index:
                index[endpoint.node_key] = graph.add_node(endpoint)
        graph.add_edge(index[edge.src.node_key], index[edge.dst.node_key], edge)

    return IndexedGraph(graph, index)
