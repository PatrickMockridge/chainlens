# `chainlens.analysis.engine`

The clustering engine: fetch, reason, merge, expand.

Clustering is iterative rather than one-shot. Merging two addresses can reveal a
third -- the change output that belongs to the enlarged cluster -- whose own
transactions may then reveal more. The engine therefore alternates between
fetching and reasoning until the cluster stops growing, bounded by explicit
budgets so a pathological address cannot run forever.

Every bound that truncates a run is reported in the result's ``warnings``. A
cluster that is small because the traversal was cut short must not look like a
cluster that is genuinely small.

## `ClusteringEngine`

```python
ClusteringEngine(provider: Provider, *, heuristics: Sequence[Heuristic] | None = None, registry: HeuristicRegistry | None = None, clusterer: Clusterer | None = None, transaction_limit: int = _DEFAULT_TRANSACTION_LIMIT, max_transactions: int = _DEFAULT_MAX_TRANSACTIONS, max_rounds: int = _DEFAULT_MAX_ROUNDS)
```

Builds the cluster around one address.

**Parameters**

- `provider` `Provider` — must advertise ``ADDRESS_TXS``; clustering needs an address's transaction history, which a bare node cannot supply.
- `heuristics` `Sequence[Heuristic] | None`, default `None` — overrides the registry's selection for the chain.
- `transaction_limit` `int`, default `_DEFAULT_TRANSACTION_LIMIT` — transactions fetched per address.
- `max_transactions` `int`, default `_DEFAULT_MAX_TRANSACTIONS` — total transactions to scan before stopping.
- `max_rounds` `int`, default `_DEFAULT_MAX_ROUNDS` — expansion rounds. Each round fetches the newly-merged addresses' histories.
- `clusterer` `Clusterer | None`, default `None` — reuse an existing clusterer, e.g. to continue from a previous run or to carry over declared non-equivalences.

**Members**

- `clusterer` = clusterer or Clusterer()
- `provider`

### `cluster`

```python
cluster(address: str, *, labels: Mapping[str, tuple[Label, ...]] | None = None) -> ClusterResult
```

Cluster the addresses sharing a controller with ``address``.

**Raises**

- `CapabilityError` — if the provider cannot list address transactions.
