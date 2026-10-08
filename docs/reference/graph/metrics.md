# `chainlens.graph.metrics`

Graph metrics: what shape is this flow graph, and where does it concentrate.

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

## `Degree`

How connected one node is.

**Attributes**

- `node_key` `str` — the node this describes.
- `in_degree` `int` — distinct sources that sent to it.
- `out_degree` `int` — distinct destinations it sent to.

**Members**

- `node_key`
- `in_degree`
- `out_degree`
- `total`

## `GraphSummary`

A structural description of a flow graph, with no units attached.

**Attributes**

- `node_count` `int` — nodes in the graph.
- `edge_count` `int` — edges in the graph.
- `density` `float` — edges over the maximum possible for this node count, 0.0 when there is only one node.
- `recurring_node_count` `int` — nodes lying on at least one cycle.
- `cycle_count` `int` — distinct cycles found, up to the enumeration limit.
- `max_in_degree` `int` — the most sources any single node has.
- `max_out_degree` `int` — the most destinations any single node has.
- `is_cyclic` `bool` — whether any cycle exists at all.

**Members**

- `node_count` = Field(ge=0)
- `edge_count` = Field(ge=0)
- `density` = Field(ge=0.0, le=1.0)
- `recurring_node_count` = Field(ge=0)
- `cycle_count` = Field(ge=0)
- `max_in_degree` = Field(ge=0)
- `max_out_degree` = Field(ge=0)
- `is_cyclic`
- `mean_out_degree`

## `NodeValue`

A node and what moved through it, in one asset's base units.

**The amount is tagged**, so a reader of "where does value concentrate" can tell a node whose
total is entirely recorded from one whose total includes a share this library inferred. See
`value_by_node`.

**Members**

- `node_key`
- `label`
- `amount`

## `betweenness`

```python
betweenness(indexed: IndexedGraph) -> Mapping[str, float]
```

Betweenness centrality per node, normalised.

High betweenness marks a node that many paths pass through -- typically a
service, and a place a trace should stop rather than expand.

## `cycles`

```python
cycles(indexed: IndexedGraph, *, limit: int = _DEFAULT_CYCLE_LIMIT) -> tuple[tuple[str, ...], ...]
```

Simple cycles as node keys, up to ``limit`` of them.

Bounded deliberately: the number of simple cycles in a dense graph grows
exponentially, and a caller wanting to look at round trips wants the first few
rather than a graph that never returns.

## `cyclic_nodes`

```python
cyclic_nodes(indexed: IndexedGraph) -> set[str]
```

Every node lying on a cycle.

## `degree_table`

```python
degree_table(indexed: IndexedGraph) -> Mapping[str, Degree]
```

Per-node in and out degree, keyed by node key.

## `density`

```python
density(indexed: IndexedGraph) -> float
```

Edge count over the maximum possible, for a directed graph without self-loops.

## `strongly_connected_components`

```python
strongly_connected_components(indexed: IndexedGraph) -> tuple[tuple[str, ...], ...]
```

Components of more than one node -- that is, nodes that can reach each other.

A component of one is just a node, so it is not reported: the question this
answers is "which nodes are in a loop", and a lone node is not.

## `summary`

```python
summary(indexed: IndexedGraph, *, cycle_limit: int = _DEFAULT_CYCLE_LIMIT) -> GraphSummary
```

Structural summary of a flow graph.

## `top_by_value`

```python
top_by_value(indexed: IndexedGraph, *, incoming: bool = True, limit: int = 10) -> tuple[NodeValue, ...]
```

The nodes moving the most value, highest first.

## `value_by_node`

```python
value_by_node(indexed: IndexedGraph, *, incoming: bool = True) -> Mapping[str, Amount]
```

Total value per node over the edges arriving at it (or leaving it), **as a tagged amount**.

**The total used to be a bare `int`, and it discarded a fact the edges were carrying.** Measured
before this changed: a node receiving 300 recorded plus 100 apportioned reported ``400``, with
no sign that a quarter of it was this library's inference from a co-funded input — while the
edges said ``apportioned = [False, True]`` all along. This module's own docstring makes exactly
that argument for *assets* ("summing edge amounts across a graph that mixes BTC and an ERC-20
... produces a number that means nothing") and did not make it for tags.

So the total is an `chainlens.models.primitives.Amount`, and `Amount.__add__` carries
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
