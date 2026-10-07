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

Merges a many-sender, single-destination address with its destination.

**Members**

- `name` = 'eth-deposit-address'
- `version` = '1'
- `chain_models` = frozenset({ChainModel.ACCOUNT})
- `minimum_senders` = 3

### `run`

```python
run(context: HeuristicContext) -> HeuristicResult
```
