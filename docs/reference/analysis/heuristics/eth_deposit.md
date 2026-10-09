# `chainlens.analysis.heuristics.eth_deposit`

Deposit-address detection on account-based chains.

Account chains have no multi-input structure, so common-input-ownership does not
apply and the standard Bitcoin clustering heuristics have no analogue. The
heuristic that does carry over is **deposit-address detection**: an address that
receives from many distinct senders and then forwards to a single destination is a
service deposit address, and shares a controller with the address it forwards to.

Two limits are worth stating plainly:

* This is a **service-level** claim, not a person-level one. It says "these two
  addresses are run by the same operator", which for an exchange is true and
  useful, and says nothing about who that operator is.
* Its confidence is deliberately modest. A retailer that receives from many
  customers and periodically sweeps to one address has the same shape as an
  exchange deposit address, and the difference is not visible on chain. Anything
  built on this should be corroborated.

## `EthDepositAddressHeuristic`

```python
EthDepositAddressHeuristic(params: EthDepositParams = DEFAULT_ETH_DEPOSIT_PARAMS)
```

Merges a many-sender, single-destination address with its destination.

**Members**

- `name` = 'eth-deposit-address'
- `version` = '1'
- `chain_models` = frozenset({ChainModel.ACCOUNT})
- `params` = params

### `run`

```python
run(context: HeuristicContext) -> HeuristicResult
```

## `EthDepositParams`

The numbers this heuristic reasons under.

The shipped values are the field defaults, and they are the only place these
numbers are written down. They were class attributes before, readable through
``self`` — the defect one notch quieter, since only a subclass could vary one.

**Attributes**

- `minimum_senders` `int` — below this many distinct senders, the pattern is indistinguishable from ordinary activity.
- `base_confidence` `float` — the confidence at the minimum sender count.
- `per_sender` `float` — how much each sender beyond the minimum adds.
- `max_confidence` `float` — the cap that climb is held to, because the shape is not evidence of *who* the operator is.

**Members**

- `minimum_senders` = Field(default=3, ge=1)
- `base_confidence` = Field(default=0.4, gt=0.0, le=1.0)
- `per_sender` = Field(default=0.05, ge=0.0)
- `max_confidence` = Field(default=0.9, gt=0.0, le=1.0)

## `DEFAULT_ETH_DEPOSIT_PARAMS`
