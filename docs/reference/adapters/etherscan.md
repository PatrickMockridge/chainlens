# `chainlens.adapters.etherscan`

Etherscan API V2.

One key covers 50+ EVM chains via a ``chainid`` parameter, so "add a chain" for an
EVM network is usually a chain id rather than a new adapter.

The module/action envelope, its three parsers and the paging are shared with every other host that
speaks the same protocol — see `chainlens.adapters._etherscan_api`. What is left here is what
is Etherscan's own: the credential, the terms that forbid redistributing its data, the free-tier
budget, and the ``proxy`` module.

:**The ``proxy`` module is why this is not just a base URL.** Etherscan answers "what is this
transaction", "what is this block" and "is there code at this address" over a JSON-RPC shim at
``?module=proxy``. Hosts that copy the flat API generally do **not** copy that, so those three
capabilities live here and only here — see `chainlens.adapters.blockscout` for the keyless
alternative and what it deliberately does not advertise.

Requires ``ETHERSCAN_API_KEY``. The key is read from settings, never from a function argument.

## `EtherscanProvider`

```python
EtherscanProvider(*, chain_id: int = 1, chain: Chain | None = None, settings: Settings | None = None, transport: Transport | None = None)
```

Ethereum (and any EVM chain Etherscan V2 serves) via the Etherscan API.

**Parameters**

- `chain_id` `int`, default `1` — the EVM chain id, 1 for Ethereum mainnet. This is the knob that makes another EVM chain work without a new adapter.
- `chain` `Chain | None`, default `None` — overrides the reported chain, for when a ``Chain`` member exists for the target network.

**Members**

- `name` = 'etherscan'
- `chain` = Chain.ETHEREUM
- `base_url` = _API_BASE
- `redistributable` = False
- `rate_limit` = _FREE_TIER

### `get_address`

```python
get_address(address: str) -> Address
```

### `get_transaction`

```python
get_transaction(txid: str) -> Transaction
```

### `get_block`

```python
get_block(reference: str | int) -> Block
```
