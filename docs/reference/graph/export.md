# `chainlens.graph.export`

Serialise a value-flow graph into formats other tools can read.

These take the pure `chainlens.models.flows.FlowGraph` rather than the
rustworkx digraph, so exporting never requires the graph engine — and a report can
be rendered from a graph that was deserialised from a file.

Every format here carries the ``txids`` alongside the amounts. A picture of money
moving is only useful if a reader can go and check, and none of these formats is
allowed to drop the thing that makes the edge falsifiable.

## `amount_label`

```python
amount_label(edge: ValueFlow) -> str
```

Render an amount, falling back to base units when decimals are unknown.

## `to_cytoscape_json`

```python
to_cytoscape_json(flow_graph: FlowGraph, *, indent: int | None = 2) -> str
```

Cytoscape.js JSON, for an interactive browser view.

## `to_dot`

```python
to_dot(flow_graph: FlowGraph) -> str
```

Graphviz DOT, for a quick static rendering.

## `to_graphml`

```python
to_graphml(flow_graph: FlowGraph) -> str
```

GraphML, for Gephi, yEd, Cytoscape desktop and igraph.

Values go in as ``long`` (integer base units) rather than formatted strings, so
a tool importing this gets numbers it can filter and size nodes by.

## `to_mermaid`

```python
to_mermaid(flow_graph: FlowGraph, *, max_nodes: int = _MERMAID_MAX_NODES) -> str
```

A Mermaid flowchart, for Markdown reports.

Node identifiers are aliased to ``n0``, ``n1``, ... because a node key contains
colons and Mermaid parses those as syntax. When the graph exceeds ``max_nodes``
it is truncated and the truncation is stated in the output, since a diagram is
the easiest artifact to mistake for a complete one.
