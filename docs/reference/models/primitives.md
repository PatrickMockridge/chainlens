# `chainlens.models.primitives`

Core chain objects: assets, inputs/outputs, transactions, addresses, blocks.

The single most important decision in this module is the reconciliation rule that
lets ONE model set serve both UTXO chains and account chains:

    Every transaction is represented canonically as a set of ``TxInput``s and
    ``TxOutput``s. UTXO chains populate them natively. Account chains are lifted
    into the same shape -- one synthesized input from ``from_address``, one
    synthesized output to ``to_address`` -- while their native fields
    (``from_address``/``to_address``/``value``/gas/``logs``) are retained and
    remain authoritative.

There is no union type and no per-chain subclass. Downstream code -- the tracer,
the graph builder, the change-address heuristic, the reporter -- reads exactly
one shape, so adding a chain never means touching the analysis layer.

Amounts are always integer base units (satoshi, wei, raw token units). Floats
never appear, because 0.1 BTC is not representable in binary floating point.

## `Address`

An address with whatever summary the provider could supply.

**Members**

- `chain`
- `address`
- `balance` = None
- `tx_count` = None
- `first_seen` = None
- `last_seen` = None
- `is_contract` = None
- `entity_id` = None
- `labels` = ()
- `provenance` = None
- `is_labeled`

## `Amount`

A magnitude, and the three things that say what it is.

The **dimension** is ``(chain, asset)`` and the **tag** is how the number was arrived at.
Both are carried, so that ``eth_amount + btc_amount`` and ``recorded + apportioned`` are
refused by the value rather than by a reader noticing a comment. See
`docs/calculus/dimensions.md` for why the first is a group and
`docs/calculus/exactness.md` for why the second is not one.

**``chain`` is here as well as on ``asset``, and that is the point rather than a
redundancy.** ``AssetRef`` carries its own chain and nothing made the two agree, so a
transfer on Bitcoin holding an Ethereum asset was constructible — and one was constructed
while the coincidence estimator was being fixed. The validator below is what refuses it, and
every model that pairs a chain with an asset carries the same one.

**Why ``asset`` is an `AssetRef` and not the vocabulary table's row id.** The plan for this
layer had it as the row id, which is the right identity for a *native* asset and does not
exist for a token: this library reads ERC-20 transfers, and a token's identity is its
contract at an address on a chain. `AssetRef` already carries exactly ``(chain, kind,
contract)``, which is that identity, and it distinguishes mainnet from testnet where a
symbol would not — two chains, after all, both write ``BTC``.

**Members**

- `chain`
- `asset`
- `base_units`
- `tag` = AmountTag.RECORDED

### `of`

```python
of(transfer: Transfer, *, tag: AmountTag | None = None) -> Amount
```

The amount a `Transfer` carries, as a value that knows what it is.

**The tag defaults to what the transfer already says and not to `RECORDED`.** A
transfer with ``ambiguous`` set is one whose sender attribution is a convention of this
library — a share of a co-funded output — and calling that recorded would be the exact
substitution the tag exists to prevent. Pass ``tag`` to override; the override is here
because a caller who has decided the apportionment is good enough should say so out
loud rather than have it inferred.

### `of_flow`

```python
of_flow(flow: ValueFlow, *, tag: AmountTag | None = None) -> Amount
```

The amount a `chainlens.models.flows.ValueFlow` carries.

The third of three adapters, and there are three because **the three models spell "how was
this arrived at" three different ways**: a transfer says ``ambiguous``, a flow says
``apportioned``, and a balance says nothing because a provider read it. Reconciling three
spellings into one tag is what an adapter is for, and it is here rather than at each call
site so that the reconciliation happens once.

### `of_balance`

```python
of_balance(balance: Balance, *, tag: AmountTag | None = None) -> Amount
```

The amount a `Balance` carries. A balance is read from a provider, so it is
recorded unless a caller says otherwise.

### `amount_to_decimal`

```python
amount_to_decimal() -> Decimal
```

Render the amount in whole units, exactly.

**Raises**

- `ValueError` — if the asset's decimals are unknown.

### `with_tag`

```python
with_tag(tag: AmountTag) -> Amount
```

The same amount, tagged differently.

For the one case where a caller changes their mind about how a figure was arrived at —
accepting an apportioned share as good enough, say. Kept as a method rather than a
mutable field so that the change is visible at the call site.

## `AssetRef`

A reference to an asset: the native coin, or a token contract.

``decimals`` is carried so an amount can be rendered exactly. It is ``None``
when the provider did not supply it, and rendering then refuses rather than
guessing -- guessing the decimals of a token is how 1 token becomes 10**18.

**Members**

- `chain`
- `kind` = AssetKind.NATIVE
- `symbol` = None
- `decimals` = None
- `contract` = None
- `token_id` = None
- `is_native`
- `is_token`

### `native`

```python
native(chain: Chain, *, symbol: str | None = None, decimals: int | None = None) -> AssetRef
```

The native coin of a chain (BTC, ETH, ...).

### `of_native`

```python
of_native(chain: Chain) -> AssetRef
```

The native coin of ``chain``, with the symbol and decimals the vocabulary table states.

**This is the constructor adapters should use**, and the other one is the reason it
exists. ``native(chain, symbol="BTC", decimals=8)`` puts two of the table's facts in an
adapter's source, and there were three adapters doing exactly that — one of which said
``"BTC"`` and ``8`` regardless of the chain it had been handed, so a Litecoin provider
described its amounts as bitcoin. Reading the row makes the adapter say nothing about
which coin it is serving.

Note what is *not* here: any fallback. A chain the table does not name raises rather
than getting a plausible-looking default, because a rendered amount in the wrong units
is a wrong answer with no symptom.

## `Balance`

An address's holdings of a single asset at a point in time.

**Members**

- `chain`
- `address`
- `asset`
- `amount`
- `block_height` = None
- `provenance` = None

### `amount_to_decimal`

```python
amount_to_decimal() -> Decimal
```

Render the amount in whole units, exactly.

**Raises**

- `ValueError` — if ``asset.decimals`` is unknown.

### `to_amount`

```python
to_amount() -> Amount
```

This balance as an `Amount`. A balance is read from a provider, so it is
recorded; `Amount.of_balance` is the same thing with the tag made explicit.

## `Block`

A block header plus whatever summary the provider supplied.

**Attributes**

- `transaction_ids` `tuple[str, ...]` — the hashes of the block's transactions, when the provider's payload carried them. An EVM node returns these for free — ``eth_getBlockByNumber`` with ``full=false`` yields hashes rather than transactions — so they are kept rather than discarded for the count, and a block number is enough to reach the transactions in the block without a full-node fetch or an index. Empty when the provider did not supply them, which is not the same as a block with no transactions: ``tx_count`` distinguishes the two.

**Members**

- `chain`
- `hash`
- `height`
- `timestamp` = None
- `tx_count` = None
- `transaction_ids` = ()
- `size` = None
- `weight` = None
- `prev_hash` = None
- `provenance` = None

## `LogEntry`

An EVM event log attached to a transaction receipt.

**Members**

- `index`
- `address` = None
- `topics` = ()
- `data` = None
- `removed` = False
- `raw` = Field(default_factory=dict)

## `MetricPoint`

A single observation of a network-level metric.

Metrics are **aggregates over the whole network**, not per-address data:
Glassnode's ``addresses.active_count`` counts active addresses network-wide.
A metric can supply report context but can never answer "what did this
address do", which is why metrics providers are a separate lane.

**Members**

- `chain`
- `metric`
- `timestamp`
- `value`
- `asset` = None
- `resolution` = None
- `provenance` = None

## `Transaction`

A transaction, in a shape that serves UTXO and account chains alike.

Fields that do not apply to a chain family are ``None``: ``gas_used`` is
``None`` on Bitcoin, ``size``/``weight`` are ``None`` on Ethereum. Nothing is
typed ``Any``; a consumer that branches on `chain_model` gets exactly
the fields that family guarantees.

**Members**

- `chain`
- `txid`
- `status` = TxStatus.CONFIRMED
- `block_hash` = None
- `block_height` = None
- `block_time` = None
- `first_seen` = None
- `confirmations` = None
- `inputs` = ()
- `outputs` = ()
- `fee` = None
- `fee_asset` = None
- `size` = None
- `vsize` = None
- `weight` = None
- `is_coinbase` = False
- `from_address` = None
- `to_address` = None
- `value` = None
- `nonce` = None
- `gas_limit` = None
- `gas_used` = None
- `gas_price` = None
- `max_fee_per_gas` = None
- `max_priority_fee_per_gas` = None
- `effective_gas_price` = None
- `contract_address` = None
- `method_id` = None
- `method_name` = None
- `logs` = ()
- `internal_transfers` = ()
- `provenance` = None
- `raw` = Field(default_factory=dict)

### `chain_model`

Derived from ``chain``, never stored, so it cannot drift out of sync.

Deliberately a plain property rather than a ``computed_field``: a computed
field is emitted by ``model_dump_json``, and re-validating that output
would then fail against ``extra="forbid"``. Since the value is fully
determined by the serialised ``chain``, leaving it out of the wire format
loses nothing and keeps round-tripping exact.

### `total_input_value`

Sum of known input values; inputs without a value contribute nothing.

### `total_output_value`

Sum of known output values.

### `input_addresses`

Every distinct address appearing on an input, in order.

### `output_addresses`

Every distinct address appearing on an output, in order.

### `counterparties`

```python
counterparties(address: str) -> tuple[str, ...]
```

The other addresses this transaction connects ``address`` to.

This is the primitive the tracer expands on: for a given participant, the
set of addresses on the opposite side of the transaction.

## `Transfer`

A single movement of value: the lowest common denominator across chains.

Both ledger models produce these. A UTXO transaction yields one per output
(change identified and flagged); an account transaction yields one for the
native value plus one per token log. This is the edge type the tracer and
the graph builder consume, which is why they never need to know which ledger
model they are looking at.

**Members**

- `chain`
- `asset`
- `amount`
- `txid`
- `src` = None
- `dst` = None
- `ambiguous` = False
- `index` = None
- `block_height` = None
- `timestamp` = None
- `via` = FlowVia.NATIVE
- `is_change` = False
- `provenance` = None

### `amount_to_decimal`

```python
amount_to_decimal() -> Decimal
```

Render the amount in whole units, exactly.

### `to_amount`

```python
to_amount() -> Amount
```

This transfer as an `Amount`, tagged by how the value was arrived at.

An ``ambiguous`` transfer is apportioned and not recorded — see
`Amount.of`, which is the same thing with the tag overridable.

## `TxInput`

A transaction input.

On UTXO chains this is a real spend of ``prev_txid:prev_vout``. On account
chains it is synthesized from the sender, and the ``prev_*`` fields are
``None``. ``value`` is ``None`` when the provider omits it -- Esplora's
``vin`` famously does not include input values, and inventing one would
corrupt every fee calculation downstream.

**Members**

- `index`
- `address` = None
- `addresses` = ()
- `value` = None
- `asset` = None
- `prev_txid` = None
- `prev_vout` = None
- `script_type` = None
- `script_hex` = None
- `script_asm` = None
- `witness` = ()
- `sequence` = None
- `is_coinbase` = False
- `raw` = Field(default_factory=dict)

### `all_addresses`

The single ``address`` plus any additional ``addresses``, de-duplicated.

## `TxOutput`

A transaction output.

``index`` is the vout index on UTXO chains and the log index on account
chains, so a ``Transfer`` can always point back at its origin.

**Members**

- `index`
- `address` = None
- `addresses` = ()
- `value` = None
- `asset` = None
- `script_type` = None
- `script_hex` = None
- `script_asm` = None
- `spent` = None
- `spent_by_txid` = None
- `spent_by_input` = None
- `raw` = Field(default_factory=dict)
- `all_addresses`

## `require_asset_on_chain`

```python
require_asset_on_chain(chain: Chain, asset: AssetRef) -> None
```

Refuse an asset that does not belong to the chain it is paired with.

**One function rather than a shared base model, and the reason is the wire contract.** A
mixin carrying the `chain` and `asset` fields would put them first in every inheriting
model, which reorders the properties in the generated JSON Schema — a diff in a committed
artefact, for a rule that has nothing to do with field order. A function per model keeps the
contract byte-identical, which is what makes this tranche's "no wire change" checkable
rather than merely intended.

One function rather than a copy of the check per model, though, because the check is one
fact and four models need it: four copies is four places for the rule to drift, which is the
failure the vocabulary table exists to prevent one layer down.

**Raises**

- `ValueError` — the asset's chain is not the chain it is paired with.
