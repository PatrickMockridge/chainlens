# `chainlens.tracing.tracer`

Bounded value-flow tracing.

The tracer walks value outward (or inward) from a seed, folding individual
transfers into aggregated `chainlens.models.flows.ValueFlow` edges and
expanding until it runs out of graph or out of budget.

Two properties are non-negotiable, and both come from the same place — a trace is
an investigative artifact that someone may act on:

* **A truncated trace says so.** ``FlowGraph.truncated`` and ``stop_reasons`` record
  how the walk ended, because a graph that is small because the budget ran out must
  never be mistaken for a graph that is genuinely small.
* **Every edge can be re-derived.** Edges carry their ``txids`` and each
  contributing transfer's ``Provenance``, so a reader can go and check rather than
  trust the picture.

When a `chainlens.analysis.clustering.Clusterer` is supplied, endpoints are
mapped through it first, so an edge can read "this entity sent to that entity" once
clustering has merged the addresses. That is what lets tracing and clustering
compose instead of each pretending the other does not exist.

One deliberate omission: **a coinbase output has no sender**, so a trace stops there
rather than inventing a source node. Walking value back to the point of minting is
a real question, and answering it badly would be worse than not answering it.

## `Tracer`

```python
Tracer(provider: Provider, *, clusterer: Clusterer | None = None, labels: Mapping[str, tuple[Label, ...]] | None = None)
```

Walks value flows from a seed address.

**Parameters**

- `provider` `Provider` — must advertise ``ADDRESS_TXS``; tracing is built on an address's transaction history, which a bare node cannot supply.
- `clusterer` `Clusterer | None`, default `None` — maps addresses to entities. Without one, every node is a single address and the result is an address graph.
- `labels` `Mapping[str, tuple[Label, ...]] | None`, default `None` — labels by address, used by the label-based stop rules and to name entity nodes.

An instance holds no state between `trace` calls; ``trace`` resets
everything it uses, so one tracer can be reused.

### `trace`

```python
trace(seed: str, *, direction: Direction = Direction.OUT, strategy: TraversalStrategy = TraversalStrategy.BREADTH_FIRST, policy: PruningPolicy | None = None, budget: TraceBudget | None = None, stop_at: frozenset[StopRule] = frozenset()) -> FlowGraph
```

Trace value flows from ``seed`` (an address).

**Raises**

- `CapabilityError` — if the provider cannot list address transactions.

## `BUDGET_DEPTH`

## `BUDGET_EDGES`

## `BUDGET_NODES`

## `BUDGET_TIME`

## `NO_HISTORY`

## `POLICY_MAX_FAN_OUT`
