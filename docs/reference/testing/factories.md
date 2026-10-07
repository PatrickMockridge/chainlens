# `chainlens.testing.factories`

Model factories for writing tests.

Small, explicit constructors so a test can build a realistic transaction without
spelling out fifteen keyword arguments. Kept in the shipped package (not in
``tests/``) because plugin authors need them too.

## `btc_transaction`

```python
btc_transaction(txid: str, outputs: Iterable[TxOutput], inputs: Iterable[TxInput] = (), *, chain: Chain = Chain.BITCOIN, block_height: int | None = None, block_time: datetime | None = None, fee: int | None = None, is_coinbase: bool = False, provenance: Provenance | None = None) -> Transaction
```

Build a UTXO-chain transaction.

## `eth_transaction`

```python
eth_transaction(txid: str, from_address: str, to_address: str | None, value: int, *, chain: Chain = Chain.ETHEREUM, block_height: int | None = None, block_time: datetime | None = None, fee: int | None = None, gas_used: int | None = None, gas_price: int | None = None, status: TxStatus = TxStatus.CONFIRMED, provenance: Provenance | None = None) -> Transaction
```

Build an account-chain transaction.

Inputs and outputs are left empty on purpose: the model lifts them into the
canonical view itself, which is the behaviour worth exercising.

## `inp`

```python
inp(index: int, address: str | None, value: int | None = None, *, prev_txid: str | None = None, prev_vout: int | None = None, is_coinbase: bool = False) -> TxInput
```

Build a transaction input.

## `make_provenance`

```python
make_provenance(provider: str = 'test', **kwargs: object) -> Provenance
```

A provenance record for fixture data.

## `out`

```python
out(index: int, address: str | None, value: int | None) -> TxOutput
```

Build a transaction output.

## `transfer`

```python
transfer(src: str | None, dst: str | None, amount: int, *, txid: str, chain: Chain = Chain.BITCOIN, via: FlowVia = FlowVia.NATIVE, asset: AssetRef | None = None, timestamp: datetime | None = None, is_change: bool = False, index: int | None = None) -> Transfer
```

Build a single value movement.
