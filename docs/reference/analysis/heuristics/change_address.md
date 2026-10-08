# `chainlens.analysis.heuristics.change_address`

Change-address detection by weighted multi-signal vote.

Identifying the change output is what stops a wallet from being fragmented into
one cluster per transaction: the change comes back to the spender, so it belongs
in the spender's cluster.

No single signal is decisive, so several are combined and scored. Two properties
matter more than the weights:

* **It abstains.** Below the threshold it returns nothing, and it also returns
  nothing when the top two candidates tie. A guess here propagates into every
  downstream cluster, so silence is the safer error.
* **It is idempotent.** Every signal is a function of the transaction and of
  externally-supplied knowledge, never of how far the caller's traversal has
  progressed. This was learned the hard way: an earlier version scored "have we
  fetched this output's address yet?", which meant re-running the detector after
  the engine expanded the cluster produced a *different* answer for the same
  transaction -- and flagged the payment recipient instead of the change.

## `ChangeAddressDetector`

Flags the change output of each UTXO transaction it can be confident about.

**Members**

- `name` = 'change-address'
- `version` = '2'
- `chain_models` = frozenset({ChainModel.UTXO})

### `run`

```python
run(context: HeuristicContext) -> HeuristicResult
```

## `flag_change_outputs`

```python
flag_change_outputs(transaction: Transaction, external_addresses: frozenset[str] = frozenset()) -> dict[int, dict[str, float]]
```

Return the change output index and the signals that voted for it.

**Parameters**

- `external_addresses` `frozenset[str]`, default `frozenset()` — addresses known to belong to someone other than the spender -- typically labeled services. A wallet's change never goes to a labeled exchange, so an output paying one is not change. This is external knowledge, not traversal state, which is what keeps the answer stable across repeated runs.

Returns an empty mapping when nothing clears the threshold, or when the top two
candidates tie.

## `is_round`

```python
is_round(value: int) -> bool
```

Whether a satoshi amount looks deliberately chosen.
