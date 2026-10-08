# `chainlens.ledger.walk`

Walking the ledger: what happened here, transaction by transaction.

A second walk alongside `chainlens.tracing.tracer`, sharing its vocabulary and
differing in what it keeps. The tracer folds movements into aggregated edges and prunes
hard, because a report has to stay readable. This keeps every recorded input and output,
because the question is "what does this transaction actually say", and folding is what
destroys the answer.

Three things it does differently, each because the alternative would be a false
statement rather than a smaller one:

**A transaction is drawn whole even when the walk is one-directional.** The tracer
filters edges by direction. Here ``direction`` decides only which addresses the frontier
expands to — never which edges are recorded. A transaction node showing only its
outgoing side is indistinguishable from a coinbase, so filtering would manufacture a
claim about the transaction rather than hide a detail.

**Nothing is apportioned.** The flow view splits a UTXO output's value across the inputs
that co-funded it, because it needs one number per address pair. A transaction node has
no such need: each edge carries what the ledger recorded for that index. What that costs
is stated on `chainlens.models.ledger` — no ledger records which input funded which
output, and the absence of a fabricated split must not be read as the ledger asserting
one.

**An amount the provider did not record stays unknown.** Esplora's ``vin`` frequently
omits input values. The flow view folds that into an apportionment; here it is
``amount_status="missing"``, and the transaction's totals become ``None`` rather than a
partial sum wearing a total's clothes.

## `FRONTIER_DEFERRED`

## `MAX_TRANSACTIONS_PER_ADDRESS`

## `PER_ADDRESS_LIMIT`

## `POLICY_COINBASE`

## `POLICY_MAX_FAN_OUT`

## `POLICY_MIN_VALUE`

## `walk_ledger`

```python
walk_ledger(provider: Provider, *, seed_address: str | None = None, seed_txids: Sequence[str] = (), direction: Direction = Direction.OUT, policy: LedgerPolicy | None = None, stop_at: frozenset[str] = frozenset()) -> LedgerGraph
```

Walk the ledger from a seed address, a set of transactions, or both.

**Parameters**

- `provider` `Provider` — must advertise ``ADDRESS_TXS`` when an address seed is given.
- `seed_address` `str | None`, default `None` — the Explore entry — an address to expand.
- `seed_txids` `Sequence[str]`, default `()` — the Verify entry — transactions placed in the graph directly, exempt from the value floor. A claim's own transaction can sit outside a dust-bounded walk, and a derivation view whose references point at nodes that are not there is worse than no view.
- `direction` `Direction`, default `Direction.OUT` — which way the frontier expands. Edges are never filtered by it.
- `policy` `LedgerPolicy | None`, default `None` — limits and pruning; defaults to the UI profile in ``LedgerPolicy``.
- `stop_at` `frozenset[str]`, default `frozenset()` — leaf reasons from `chainlens.tracing.strategy.StopRule`. A matching address is admitted and not expanded.

**Raises**

- `CapabilityError` — an address seed was given and the provider cannot list one's transactions.
- `ValueError` — neither a seed address nor a seed transaction was given.
