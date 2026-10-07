# `chainlens.analysis.clustering`

Address clustering: union-find, evidence application, and result types.

A cluster is a *hypothesis* that several addresses share one controller. Three
properties of this module follow from taking that seriously:

* **Every merge carries its justification.** A merge without evidence is an
  assertion, and the engine exists to avoid those.
* **Conflicts are refused, not averaged.** Two addresses with high-confidence
  evidence that they are *different* entities are never unioned, however many
  weaker heuristics suggest otherwise.
* **A cluster is as strong as its weakest link.** Aggregated confidence is the
  *minimum* over the merges that built it, not the mean or the maximum: a chain of
  individually-plausible merges is exactly where errors compound, and averaging
  would hide that.

Entity identifiers are derived from cluster membership rather than assigned
sequentially, so the same cluster gets the same id on every run and in every
process. That is what makes a report reproducible.

## `AppliedResult`

What the clusterer did with one heuristic's output.

**Members**

- `heuristic`
- `merges_applied` = 0
- `merges_refused` = 0
- `warnings` = ()

## `ClusterResult`

Everything a clustering run produced, plus what it cost.

**Members**

- `chain`
- `seed`
- `entities` = ()
- `observations` = ()
- `refusals` = ()
- `warnings` = ()
- `transactions_scanned` = 0
- `addresses_considered` = 0
- `rounds` = 0
- `converged` = False
- `cluster_size`

### `cluster_of_seed`

The seed's cluster, or just the seed if nothing merged with it.

## `Clusterer`

```python
Clusterer(non_equivalent: Iterable[tuple[str, str, str]] = ())
```

Applies heuristic output to a union-find, with evidence and refusals.

**Parameters**

- `non_equivalent` `Iterable[tuple[str, str, str]]`, default `()` — pairs that must never be merged, as ``(address_a, address_b, reason)``. This encodes "these two are known to be different entities" -- a labeled exchange and a labeled mixer, say -- so a weak heuristic cannot override established knowledge.

**Members**

- `union_find`
- `heuristics_applied`
- `blocked_pairs`

### `applied_merges`

Every merge that took effect, with the evidence that justified it.

### `refusals`

Every merge that was forbidden by a declared non-equivalence.

### `block`

```python
block(address_a: str, address_b: str, reason: str) -> None
```

Record that two addresses are known to be different entities.

### `union`

```python
union(address_a: str, address_b: str, *, confidence: float, heuristic: str, detail: Mapping[str, Any] | None = None, txids: tuple[str, ...] = ()) -> bool
```

Merge two addresses, honouring any non-equivalence declaration.

A refusal does not raise: a heuristic proposing a forbidden merge is a
finding to report, not a crash.

### `apply_merge`

```python
apply_merge(merge: Merge) -> bool
```

Apply a merge assertion, unless a declared conflict forbids it.

### `apply`

```python
apply(result: HeuristicResult) -> AppliedResult
```

Apply everything a heuristic run produced.

### `fold_change_outputs`

```python
fold_change_outputs(transactions: Mapping[str, Transaction], change_flags: Mapping[str, frozenset[int]], *, heuristic: str = 'change-address', confidence: float = 0.7) -> int
```

Merge each detected change output back into its sender's cluster.

A change output is by definition paid back to the spender, so leaving it
separate would fragment a wallet into one cluster per transaction -- which
is the false pattern change detection exists to prevent.

Returns the number of change outputs folded.

### `members`

```python
members(address: str) -> frozenset[str]
```

The cluster containing ``address``. A lone address is its own cluster.

### `cluster_id`

```python
cluster_id(members: frozenset[str]) -> str
```

A stable identifier for a set of addresses.

Derived from membership, so the same cluster has the same id across runs
and processes. A sequential counter would make reports irreproducible.

### `entities`

```python
entities(*, chain: Chain, labels: Mapping[str, tuple[Label, ...]] | None = None, minimum_size: int = 2) -> tuple[Entity, ...]
```

Build one `Entity` per cluster.

**Parameters**

- `minimum_size` `int`, default `2` — clusters smaller than this are omitted. The default of 2 means a lone address yields no entity -- there is nothing to assert about a cluster of one.

### `confidence_for`

```python
confidence_for(members: frozenset[str]) -> float
```

The weakest link among the merges that built this cluster.

An average would overstate a cluster assembled from one strong merge and
several speculative ones.

## `Refusal`

A merge that was proposed and rejected because of a known conflict.

**Members**

- `addresses`
- `heuristic`
- `reason`

## `UnionFind`

```python
UnionFind()
```

Disjoint sets with path compression and union by size.

Deliberately a plain data structure with no notion of evidence, confidence or
refusal -- that policy lives in `Clusterer`. Keeping them apart is what
makes the union-find's invariants testable in isolation.

### `find`

```python
find(item: str) -> str
```

Return the representative of ``item``'s set, registering it if new.

### `add`

```python
add(item: str) -> str
```

Register ``item`` without merging it with anything.

### `union`

```python
union(a: str, b: str) -> bool
```

Merge two sets. Returns ``True`` if they were previously distinct.

### `connected`

```python
connected(a: str, b: str) -> bool
```

Whether two items are in the same set. Unknown items are not connected.

### `members`

```python
members(item: str) -> frozenset[str]
```

Every item in ``item``'s set, including ``item`` itself.

### `components`

```python
components() -> dict[str, frozenset[str]]
```

Map each representative to its members.
