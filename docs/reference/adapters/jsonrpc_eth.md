# `chainlens.adapters.jsonrpc_eth`

Ethereum over raw JSON-RPC.

Implemented against the transport directly rather than through ``web3.py``: six
methods are needed, the transport already provides caching, retries and rate
limiting, and ``web3.py`` would pull a large dependency tree into everyone's
install, including Bitcoin-only users. ``web3.py`` remains available behind the
``[eth]`` extra for ABI decoding, which is the part that is genuinely hard.

**This provider does not advertise ``ADDRESS_TXS``, and that is the point.** A node
can answer "what is this transaction" and "what is this address's balance"; it
cannot answer "list every transaction this address ever made", because there is no
index. Enumerating would mean scanning blocks. Rather than return a partial or
misleading list, the capability is simply not claimed, and the
`chainlens.providers.composite.CompositeProvider` routes that question to a
provider that can answer it.

``get_token_transfers`` is implemented via ``eth_getLogs``, which is a genuine
capability but a fragile one: public endpoints commonly cap the block range or
result count and will reject a full-history query. It works on an archive or
full node, and the docstring says so.

## `JsonRpcEthProvider`

```python
JsonRpcEthProvider(*, rpc_url: str | None = None, chain: Chain | None = None, settings: Settings | None = None, transport: Transport | None = None)
```

Ethereum via a JSON-RPC node.

**Parameters**

- `rpc_url` `str | None`, default `None` — overrides ``CHAINLENS_ETH_RPC_URL``. Defaults are public and rate-limited; pointing this at your own node is the way to remove the ceiling and to be able to use ``get_token_transfers``.

**Members**

- `name` = 'jsonrpc-eth'
- `chain` = Chain.ETHEREUM
- `redistributable` = True
- `rate_limit` = _DEFAULT_RATE_LIMIT
- `rpc_url` = url

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

### `get_token_transfers`

```python
get_token_transfers(address: str, *, limit: int | None = None, cursor: str | None = None) -> AsyncIterator[Transfer]
```

Yield ERC-20 transfers touching an address via ``eth_getLogs``.

Issues two log queries (incoming, then outgoing) because a topic filter
matches positionally, then de-duplicates on ``(txid, logIndex)`` -- a
self-transfer would otherwise appear in both.

**Requires a full or archive node.** Public endpoints typically cap the
block range or the result count for ``eth_getLogs`` and will reject a
full-history query; on those, prefer a provider that keeps an index.
``from_block``/``to_block`` cannot be narrowed through this interface.

### `aclose`

```python
aclose() -> None
```
