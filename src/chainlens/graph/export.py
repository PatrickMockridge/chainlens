"""Serialise a value-flow graph into formats other tools can read.

These take the pure :class:`~chainlens.models.flows.FlowGraph` rather than the
rustworkx digraph, so exporting never requires the graph engine — and a report can
be rendered from a graph that was deserialised from a file.

Every format here carries the ``txids`` alongside the amounts. A picture of money
moving is only useful if a reader can go and check, and none of these formats is
allowed to drop the thing that makes the edge falsifiable.
"""

from __future__ import annotations

from decimal import Decimal
from xml.sax.saxutils import escape, quoteattr

# The strict-JSON discipline lives with the wire contract rather than here: one implementation of
# "JSON a strict parser accepts", used by every exporter, so a second one cannot drift from it.
from chainlens.ledger.schema import strict_json
from chainlens.models.flows import AddressRef, EntityRef, FlowGraph, NodeRef, ValueFlow

__all__ = ["amount_label", "to_cytoscape_json", "to_dot", "to_graphml", "to_mermaid"]

#: Mermaid lays out every node before rendering, so a large graph produces output
#: no browser will open. Beyond this the diagram is truncated and says so.
_MERMAID_MAX_NODES = 200


def _label(node: NodeRef) -> str:
    """A short human label for a node."""
    if isinstance(node, EntityRef):
        return node.label or f"entity {node.entity_id}"
    return node.address


def _node_kind(node: NodeRef) -> str:
    return "entity" if isinstance(node, EntityRef) else "address"


def _addresses(node: NodeRef) -> tuple[str, ...]:
    """Member addresses, for an entity only where the ref can supply them.

    ``EntityRef`` carries an id rather than its members, so an entity node exports
    its id and label; the addresses are resolvable through the clusterer that
    produced the graph.
    """
    return (node.address,) if isinstance(node, AddressRef) else ()


def amount_label(edge: ValueFlow) -> str:
    """Render an amount, falling back to base units when decimals are unknown."""
    try:
        rendered: Decimal = edge.amount_to_decimal()
    except ValueError:
        symbol = edge.asset.symbol or str(edge.asset.kind)
        return f"{edge.amount} {symbol} (base units)"
    symbol = edge.asset.symbol or str(edge.asset.kind)
    return f"{rendered:f} {symbol}"


def to_graphml(flow_graph: FlowGraph) -> str:
    """GraphML, for Gephi, yEd, Cytoscape desktop and igraph.

    Values go in as ``long`` (integer base units) rather than formatted strings, so
    a tool importing this gets numbers it can filter and size nodes by.
    """
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        '<key id="n_label" for="node" attr.name="label" attr.type="string"/>',
        '<key id="n_kind" for="node" attr.name="kind" attr.type="string"/>',
        '<key id="n_address" for="node" attr.name="address" attr.type="string"/>',
        '<key id="e_amount" for="edge" attr.name="amount" attr.type="long"/>',
        '<key id="e_asset" for="edge" attr.name="asset" attr.type="string"/>',
        '<key id="e_txids" for="edge" attr.name="txids" attr.type="string"/>',
        '<key id="e_hops" for="edge" attr.name="hops" attr.type="int"/>',
        '<key id="e_confidence" for="edge" attr.name="confidence" attr.type="double"/>',
        '<key id="e_change" for="edge" attr.name="change" attr.type="boolean"/>',
        '<graph edgedefault="directed">',
    ]

    for node in flow_graph.nodes:
        lines.append(f"<node id={quoteattr(node.node_key)}>")
        lines.append(f'<data key="n_label">{escape(_label(node))}</data>')
        lines.append(f'<data key="n_kind">{_node_kind(node)}</data>')
        lines.extend(
            f'<data key="n_address">{escape(address)}</data>' for address in _addresses(node)
        )
        lines.append("</node>")

    for edge in flow_graph.edges:
        lines.append(
            f"<edge source={quoteattr(edge.src.node_key)} target={quoteattr(edge.dst.node_key)}>"
        )
        lines.append(f'<data key="e_amount">{edge.amount}</data>')
        lines.append(f'<data key="e_asset">{escape(str(edge.asset.kind))}</data>')
        lines.append(f'<data key="e_txids">{escape(",".join(edge.txids))}</data>')
        lines.append(f'<data key="e_hops">{edge.hops}</data>')
        lines.append(f'<data key="e_confidence">{edge.confidence}</data>')
        lines.append(f'<data key="e_change">{str(edge.is_change).lower()}</data>')
        lines.append("</edge>")

    lines.extend(["</graph>", "</graphml>"])
    return "\n".join(lines) + "\n"


def to_cytoscape_json(flow_graph: FlowGraph, *, indent: int | None = 2) -> str:
    """Cytoscape.js JSON, for an interactive browser view."""
    nodes = [
        {
            "data": {
                "id": node.node_key,
                "label": _label(node),
                "kind": _node_kind(node),
                "addresses": list(_addresses(node)),
            }
        }
        for node in flow_graph.nodes
    ]
    edges = [
        {
            "data": {
                "id": f"{edge.src.node_key}->{edge.dst.node_key}:{edge.asset.kind}",
                "source": edge.src.node_key,
                "target": edge.dst.node_key,
                "amount": edge.amount,
                "amount_label": amount_label(edge),
                "asset": str(edge.asset.kind),
                "txids": list(edge.txids),
                "n_transfers": edge.n_transfers,
                "hops": edge.hops,
                "confidence": edge.confidence,
                # Read off the field rather than inferred from the confidence. The two agree
                # by construction — `confidence` derives from this — and the flag is the one
                # that says what it means, where a float comparison said it by arithmetic.
                "apportioned": edge.apportioned,
            }
        }
        for edge in flow_graph.edges
    ]
    return strict_json({"elements": {"nodes": nodes, "edges": edges}}, indent=indent)


def _dot_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _dot_node(node: NodeRef) -> str:
    shape = "ellipse" if isinstance(node, EntityRef) else "box"
    return f'  "{_dot_escape(node.node_key)}" [label="{_dot_escape(_label(node))}", shape={shape}];'


def _dot_edge(edge: ValueFlow) -> str:
    return (
        f'  "{_dot_escape(edge.src.node_key)}" -> "{_dot_escape(edge.dst.node_key)}" '
        f'[label="{_dot_escape(amount_label(edge))}"];'
    )


def to_dot(flow_graph: FlowGraph) -> str:
    """Graphviz DOT, for a quick static rendering."""
    lines = ["digraph flows {", "  rankdir=LR;", "  node [shape=box];"]
    lines.extend(_dot_node(node) for node in flow_graph.nodes)
    lines.extend(_dot_edge(edge) for edge in flow_graph.edges)
    lines.append("}")
    return "\n".join(lines) + "\n"


def _mermaid_safe(text: str) -> str:
    """Mermaid labels break on quotes and angle brackets."""
    return text.replace('"', "'").replace("<", "(").replace(">", ")")


def to_mermaid(flow_graph: FlowGraph, *, max_nodes: int = _MERMAID_MAX_NODES) -> str:
    """A Mermaid flowchart, for Markdown reports.

    Node identifiers are aliased to ``n0``, ``n1``, ... because a node key contains
    colons and Mermaid parses those as syntax. When the graph exceeds ``max_nodes``
    it is truncated and the truncation is stated in the output, since a diagram is
    the easiest artifact to mistake for a complete one.
    """
    nodes = flow_graph.nodes[:max_nodes]
    included = {node.node_key for node in nodes}
    aliases = {node.node_key: f"n{position}" for position, node in enumerate(nodes)}

    lines = ["flowchart LR"]
    if len(flow_graph.nodes) > max_nodes:
        lines.append(f"  %% truncated: showing {max_nodes} of {len(flow_graph.nodes)} nodes")
    lines.extend(f'  {aliases[node.node_key]}["{_mermaid_safe(_label(node))}"]' for node in nodes)

    for edge in flow_graph.edges:
        if edge.src.node_key not in included or edge.dst.node_key not in included:
            continue
        label = _mermaid_safe(amount_label(edge))
        lines.append(f'  {aliases[edge.src.node_key]} -->|"{label}"| {aliases[edge.dst.node_key]}')
    return "\n".join(lines) + "\n"
