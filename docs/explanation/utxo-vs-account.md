# UTXO vs account models

Bitcoin and Ethereum record ownership in fundamentally different ways, and almost
every chain-analysis library ends up with two parallel implementations because of
it. `chainlens` makes one design decision to avoid that, and it is worth
understanding because it shapes the entire API.

## The two models

**UTXO (Bitcoin).** There are no balances, only *unspent transaction outputs*. A
transaction consumes outputs as inputs and creates new outputs. An address's
"balance" is the sum of the outputs it can still spend.

**Account (Ethereum).** Each address has a balance, a nonce, and optional code.
A transaction is a message from one account to another.

## The reconciliation rule

> Every transaction is represented canonically as a set of inputs and outputs.
> UTXO chains populate them natively. Account chains are **lifted** into the same
> shape — one synthesized input from `from_address`, one synthesized output to
> `to_address` — while their native fields remain authoritative.

There is no union type and no per-chain subclass. A transaction carries a derived
`chain_model` saying which family it is:

```python
tx.chain_model is ChainModel.UTXO      # native input/output view is real
tx.chain_model is ChainModel.ACCOUNT   # native fields are authoritative;
                                       # the input/output view is synthesized
```

## Why synthesized inputs carry the fee

The synthesized input for an account-chain transaction carries `value + fee`.
That is a deliberate choice: it means the pseudo-UTXO view *conserves value*, so
a naive consistency check holds on both families:

```python
tx.total_input_value - tx.total_output_value == tx.fee
```

Without that, the same validation logic would silently mean different things on
different chains — exactly the class of bug this design exists to prevent.

## What this buys

The tracer, the graph builder, the change-address heuristic and the reporter all
read **one** shape. Adding a chain means writing a provider that maps its data
into this shape; it does not mean touching the analysis layer. The value-flow
edge type is the same idea one level up:

```python
from chainlens.models.flows import AddressRef, EntityRef

# A flow endpoint is an address *or* an entity (a cluster). Once two addresses
# are merged into one entity, the graph says "this entity sent 3.4 BTC to that
# entity" rather than pretending they are still separate actors.
```

## What it costs

A consumer that needs a field unique to one family must branch on `chain_model`
— for example, `gas_used` is always `None` on Bitcoin and `size`/`weight` are
always `None` on Ethereum. Nothing is typed `Any`; the fields that do not apply
are `None`, so the branch is visible in the type system rather than implicit.
