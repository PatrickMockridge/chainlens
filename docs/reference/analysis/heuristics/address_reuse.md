# `chainlens.analysis.heuristics.address_reuse`

Address reuse: observations, not merges.

The original plan for this heuristic was to merge, and that turned out to be wrong
for a reason worth recording rather than quietly dropping.

The two standard reuse patterns are an address spending as an input in more than
one transaction, and an address that receives and later spends. Neither yields a
*safe* merge:

* An address appearing as an input in several transactions is simply one address.
  There is nothing to merge.
* The tempting extension -- "an address that received and later spends links its
  earlier counterparties to its later ones" -- is unsound. When a merchant's
  receiving address is later swept, the other outputs of the *receiving*
  transaction include the payer's change. Merging those would attribute the
  payer's wallet to the merchant. (It would otherwise be subsumed anyway: the
  reuse address is an input of the later transaction, so
  common-input-ownership already merges it with that transaction's other inputs.)

What reuse *does* establish is characterisation rather than identity: a reused
input address is an operational address rather than a one-shot, and an address
that receives and later spends is a wallet rather than a deposit sink. Those are
observations about behaviour, so this heuristic emits labels and performs no
merges. The happy consequence is that it cannot contribute a false merge.

## `AddressReuse`

```python
AddressReuse(params: AddressReuseParams = DEFAULT_ADDRESS_REUSE_PARAMS)
```

Labels reused addresses and receive-then-spend behaviour.

Emits no merges by design -- see the module docstring.

**Members**

- `name` = 'address-reuse'
- `version` = '1'
- `chain_models` = frozenset()
- `params` = params

### `run`

```python
run(context: HeuristicContext) -> HeuristicResult
```

## `AddressReuseParams`

The confidences the two reuse observations carry.

The shipped values are the field defaults, and they are the only place these
numbers are written down.

**Attributes**

- `reuse_confidence` `float` — for an address spent as an input more than once.
- `received_then_spent_confidence` `float` — for an address that received and later spent, which is a slightly weaker observation -- the order is inferred from block heights, so a missing height removes the label entirely.

**Members**

- `reuse_confidence` = Field(default=0.9, gt=0.0, le=1.0)
- `received_then_spent_confidence` = Field(default=0.85, gt=0.0, le=1.0)

## `DEFAULT_ADDRESS_REUSE_PARAMS`

## `RECEIVED_THEN_SPENT`

## `REUSED_INPUT`
