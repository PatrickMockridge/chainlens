"""Graph algorithms and serialisation over a value-flow graph.

The data model lives in :mod:`chainlens.models.flows`; this package turns it into
an indexed digraph for algorithms (:mod:`~chainlens.graph.build`,
:mod:`~chainlens.graph.metrics`) and into text formats for handing to other tools
(:mod:`~chainlens.graph.export`).
"""

from __future__ import annotations

from chainlens.graph.build import IndexedGraph, to_rustworkx
from chainlens.graph.export import (
    to_cytoscape_json,
    to_dot,
    to_graphml,
    to_mermaid,
)
from chainlens.graph.metrics import (
    Degree,
    GraphSummary,
    NodeValue,
    betweenness,
    cycles,
    cyclic_nodes,
    degree_table,
    density,
    strongly_connected_components,
    summary,
    top_by_value,
    value_by_node,
)

__all__ = [
    "Degree",
    "GraphSummary",
    "IndexedGraph",
    "NodeValue",
    "betweenness",
    "cycles",
    "cyclic_nodes",
    "degree_table",
    "density",
    "strongly_connected_components",
    "summary",
    "to_cytoscape_json",
    "to_dot",
    "to_graphml",
    "to_mermaid",
    "to_rustworkx",
    "top_by_value",
    "value_by_node",
]
