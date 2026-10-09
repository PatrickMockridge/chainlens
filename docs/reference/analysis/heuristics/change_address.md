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

```python
ChangeAddressDetector(params: ChangeAddressParams = DEFAULT_CHANGE_ADDRESS_PARAMS)
```

Flags the change output of each UTXO transaction it can be confident about.

**Members**

- `name` = 'change-address'
- `version` = '2'
- `chain_models` = frozenset({ChainModel.UTXO})
- `params` = params

### `run`

```python
run(context: HeuristicContext) -> HeuristicResult
```

## `ChangeAddressParams`

The numbers this heuristic reasons under.

The shipped values are the field defaults, and they are the only place these
numbers are written down.

**Attributes**

- `round_unit` `int` — a value divisible by this is "round" — a payment someone chose, rather than the remainder of one. 0.1 BTC by default, which presumes eight decimals; see the page for why that makes it chain-relative in disguise.
- `weights` `Mapping[str, float]` — each signal's contribution. They sum to more than 1 on purpose; the total is clipped, so a transaction firing every signal scores 1.0 rather than 1.15.
- `threshold` `float` — below this the detector says nothing.

**Members**

- `round_unit` = Field(default=10000000, ge=1)
- `weights` = Field(default_factory=lambda: {'script_type_matches_inputs': 0.35, 'output_not_a_known_external_address': 0.25, 'smaller_than_smallest_input': 0.2, 'non_round_among_round': 0.2, 'two_outputs': 0.15})
- `threshold` = Field(default=0.5, ge=0.0, le=1.0)

## `DEFAULT_CHANGE_ADDRESS_PARAMS`

## `flag_change_outputs`

```python
flag_change_outputs(transaction: Transaction, external_addresses: frozenset[str] = frozenset(), *, params: ChangeAddressParams = DEFAULT_CHANGE_ADDRESS_PARAMS) -> dict[int, dict[str, float]]
```

Return the change output index and the signals that voted for it.

**Parameters**

- `external_addresses` `frozenset[str]`, default `frozenset()` — addresses known to belong to someone other than the spender -- typically labeled services. A wallet's change never goes to a labeled exchange, so an output paying one is not change. This is external knowledge, not traversal state, which is what keeps the answer stable across repeated runs.

Returns an empty mapping when nothing clears the threshold, or when the top two
candidates tie.

## `is_round`

```python
is_round(value: int, *, params: ChangeAddressParams = DEFAULT_CHANGE_ADDRESS_PARAMS) -> bool
```

Whether a satoshi amount looks deliberately chosen.
