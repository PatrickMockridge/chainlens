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

## `Block`

A block header plus whatever summary the provider supplied.

**Members**

- `chain`
- `hash`
- `height`
- `timestamp` = None
- `tx_count` = None
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
