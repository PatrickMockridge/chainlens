# `chainlens.adapters.etherscan`

Etherscan API V2.

One key covers 50+ EVM chains via a ``chainid`` parameter, so "add a chain" for an
EVM network is usually a chain id rather than a new adapter.

Two schema traps this module exists to absorb:

* ``status: "0"`` is **not** always an error. An address with no transactions
  returns ``{"status": "0", "message": "No transactions found", "result": []}``.
  Treating that as a failure would make every empty wallet look like a broken
  request.
* Addresses arrive lowercase and are kept that way. EIP-55 checksumming is for
  display; normalising to the canonical lowercase form is what lets a transaction
  fetched here compare equal to the same transaction fetched over JSON-RPC.

Requires ``ETHERSCAN_API_KEY``. The key is read from settings, never from a
function argument.

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

### `get_balance`

```python
get_balance(address: str) -> Balance
```

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

### `get_address_transactions`

```python
get_address_transactions(address: str, *, limit: int | None = None, cursor: str | None = None, since: Any = None, until: Any = None) -> AsyncIterator[Transaction]
```

Yield an address's transactions, newest first.

Etherscan pages by number, so the cursor is the page index as a string.

### `get_token_transfers`

```python
get_token_transfers(address: str, *, limit: int | None = None, cursor: str | None = None) -> AsyncIterator[Transfer]
```

Yield ERC-20 transfers touching an address, newest first.

Note this is ERC-20 only. Etherscan exposes ERC-721 and ERC-1155 transfers
through separate endpoints (``tokennfttx``, ``tokennfttx``/``token1155tx``)
which this adapter does not yet read; they are not silently merged in.

### `aclose`

```python
aclose() -> None
```
