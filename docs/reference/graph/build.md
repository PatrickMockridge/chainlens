# `chainlens.graph.build`

Build a rustworkx digraph from a `chainlens.models.flows.FlowGraph`.

The graph engine is deliberately *not* part of the data model. A ``FlowGraph`` is
pure pydantic data that can be serialised, snapshotted and compared; this module
turns it into an indexed digraph for algorithms. That way the backend can be
replaced without touching tracing or reporting, and most tests never need
rustworkx at all.

rustworkx was chosen over networkx because a depth-5 trace off a busy address
routinely reaches six figures of nodes, where networkx's pure-Python traversal
becomes the bottleneck. ``networkx`` remains available through the ``[nx]`` extra
for its ecosystem and layout algorithms.

## `IndexedGraph`

```python
IndexedGraph(graph: rx.PyDiGraph, index: Mapping[str, int])
```

A rustworkx digraph plus the node-key index it was built with.

rustworkx addresses nodes by integer position, so every caller needs the
key-to-position map. Keeping it here, next to the graph it describes, is what
stops that map from being rebuilt inconsistently -- or off by one -- at each
call site.

**Members**

- `node_count`
- `edge_count`

### `graph`

The underlying digraph. Node and edge payloads are chainlens models.

### `keys`

```python
keys() -> tuple[str, ...]
```

Every node key, in position order.

### `index_of`

```python
index_of(node_key: str) -> int | None
```

The digraph position of a node, or ``None`` if it is not present.

### `key_of`

```python
key_of(position: int) -> str
```

### `node_at`

```python
node_at(position: int) -> NodeRef
```

The node payload at a position.

Validated rather than cast: rustworkx payloads are untyped, so a graph built
by anything other than `to_rustworkx` could hold something else, and
failing here with a clear message beats an ``AttributeError`` three layers
up.

### `edge_payload`

```python
edge_payload(src_key: str, dst_key: str) -> ValueFlow | None
```

The `ValueFlow` on an edge, or ``None`` if there is no such edge.

### `in_degree`

```python
in_degree(node_key: str) -> int
```

### `out_degree`

```python
out_degree(node_key: str) -> int
```

## `to_rustworkx`

```python
to_rustworkx(flow_graph: FlowGraph) -> IndexedGraph
```

Build an `IndexedGraph` from a value-flow graph.

Node payloads are the `chainlens.models.flows.NodeRef` objects and edge
payloads are the `ValueFlow` objects, so an algorithm result can be
traced straight back to the evidence it came from.

An edge endpoint missing from ``flow_graph.nodes`` is added rather than the
edge being dropped: silently discarding an edge would change the answer, and a
quietly incomplete graph is the failure mode this library works hardest to
avoid.
