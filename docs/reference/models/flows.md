# `chainlens.models.flows`

Value-flow graph vocabulary, and the derivation of flows from transactions.

A `ValueFlow` endpoint is a `NodeRef`, which is *either* a raw
address or an entity (a cluster of addresses believed to share a controller).
That choice is what lets tracing compose with clustering: once two addresses are
merged into one entity, the graph can say "this entity sent 3.4 BTC to that
entity" instead of pretending they are still separate actors.

``NodeRef`` is a discriminated union on the ``kind`` literal, so pydantic round
trips it without a caller having to guess which arm a dict represents.

Everything here is pure data plus pure functions over it. The graph algorithms and
serialisers live in `chainlens.graph`, so the backend can change without
touching this module.

## `AddressRef`

A graph node that is a single address.

**Members**

- `kind` = 'address'
- `chain`
- `address`

### `node_key`

Stable identity string, suitable as a dict key across runs.

## `EntityRef`

A graph node that is a cluster of addresses.

``label`` is a display convenience only; the identity is ``entity_id``.

The member addresses are deliberately **not** carried here. Every edge holds
two node refs, so an address set on each of them would duplicate the whole
cluster once per edge — and a graph can have a great many edges. Resolve an
``entity_id`` back to its addresses through the
`chainlens.analysis.clustering.Clusterer` that produced it, or through
the `chainlens.models.entities.Entity` objects on a report.

**Members**

- `kind` = 'entity'
- `chain`
- `entity_id`
- `label` = None
- `node_key`

## `FlowGraph`

The result of a trace: nodes, aggregated edges, and how the run ended.

Pure data, so the graph backend and serialisers can change independently.

``truncated`` and ``stop_reasons`` exist because a partial graph that *looks*
complete is the most misleading artifact this library can produce. A caller
must be able to tell "there is nothing more here" from "we stopped looking".

**Members**

- `chain`
- `seed`
- `nodes` = ()
- `edges` = ()
- `depth_reached` = 0
- `expanded_addresses` = 0
- `truncated` = False
- `stop_reasons` = Field(default_factory=dict)
- `warnings` = ()
- `elapsed_seconds` = None
- `node_count`
- `edge_count`
- `is_empty`

### `outgoing`

```python
outgoing(node_key: str) -> tuple[ValueFlow, ...]
```

Edges leaving ``node_key``.

### `incoming`

```python
incoming(node_key: str) -> tuple[ValueFlow, ...]
```

Edges arriving at ``node_key``.

### `neighbours`

```python
neighbours(node_key: str) -> tuple[str, ...]
```

Distinct node keys reachable from ``node_key``, sorted for stability.

### `total_value`

```python
total_value() -> int
```

Sum of every edge's amount, in base units.

Meaningful only within one asset; a graph mixing BTC and an ERC-20 would
add different units together, which is why the report groups by asset.

### `assets`

```python
assets() -> tuple[AssetRef, ...]
```

The distinct assets appearing on any edge.

## `ValueFlow`

An aggregated movement of value between two graph nodes.

Individual transfers between the same pair of nodes (possibly across many
transactions) are folded into one edge, with ``n_transfers`` and ``txids``
recording what was combined. ``path`` records the ordered node keys from the
trace root to this edge, which is what makes path-based reporting possible
without re-running the traversal.

**Members**

- `chain`
- `src`
- `dst`
- `asset`
- `amount`
- `n_transfers` = 1
- `txids` = ()
- `first_seen` = None
- `last_seen` = None
- `hops` = 0
- `direction` = FlowDirection.OUT
- `via` = FlowVia.NATIVE
- `path` = ()
- `is_change` = False
- `apportioned` = False
- `heuristics` = ()
- `provenance` = None

### `confidence`

How much of this edge the chain recorded, as the flow view has always spelled it.

**It is a convention and not a measurement, and that is what this property is here to
say.** The value is 1.0 or 0.5 and nothing else — there is no estimator behind it and
never was one — so as a stored field it read as a confidence the library had measured.
The field is `apportioned`; this derives from it, one way, so the two cannot
disagree.

It survives at all because two exports publish it: the GraphML and the JSON both carry
a `confidence` per edge, and dropping a field consumers may read is a different change
from stopping the library from implying it measured something.

### `amount_to_decimal`

```python
amount_to_decimal() -> Decimal
```

Render the amount in whole units, exactly.

### `edge_key`

Identity of this edge: ``(src, dst, asset-ish)``.

### `is_self_loop`

Whether both endpoints are the same node (a change output, typically).

## `APPORTIONED_CONFIDENCE`

## `DIRECT_CONFIDENCE`

## `NodeRef`

## `largest_remainder_split`

```python
largest_remainder_split(total: int, weights: Sequence[int]) -> list[int]
```

Split ``total`` across ``weights`` proportionally, summing back to ``total``.

Integer apportionment that neither loses nor invents a unit: take the floors,
then hand the remaining units to the largest fractional parts, breaking ties by
index so the result is deterministic.

Plain rounding would not sum to the total, and a tracer that does not conserve
value is worse than no tracer at all. Falls back to an equal split when the
weights carry no information (all zero), and raises on an empty weight list
rather than returning something meaningless.

## `transfers_from_transaction`

```python
transfers_from_transaction(transaction: Transaction, *, change_indexes: frozenset[int] = frozenset()) -> tuple[Transfer, ...]
```

Derive the value movements a transaction represents.

This is where the two ledger models converge onto the one edge type the tracer,
the graph and the reporter all consume.

**UTXO attribution is an apportionment, not a reading.** Nothing on chain says
which input funded which output. When several addresses co-fund a transaction,
each output's value is split across them in proportion to what they put in,
using integer largest-remainder rounding.

The guarantee is exact **per output**: every output's value is fully
attributed, so "how much did this address receive" is precise to the base unit.
The margin **per sender** is approximate. Rounding each output independently
means a sender's shares can drift by up to one base unit per output — with two
senders and two outputs, an address that put in 100 may be credited 101. This
is stated rather than hidden because it is a real bound on what these figures
support, and because eliminating it would need a two-dimensional rounding whose
extra complexity the tracer does not need: it follows outgoing value, so the
recipient margin is the one that matters.

The resulting transfers are marked
`chainlens.models.primitives.Transfer.ambiguous`, because a reader is
entitled to know that the split is our inference and not the ledger's.

**Parameters**

- `change_indexes` `frozenset[int]`, default `frozenset()` — output indexes already identified as change, so the edge can be flagged as value returning to its sender.

**Returns**

- `` `Transfer` — The transfers, possibly empty. ERC-20 movements are **not** derived here:
- `` `...` — they come from logs, which adapters expose through ``get_token_transfers``.
