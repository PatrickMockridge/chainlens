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

### `get_window_transfers`

```python
get_window_transfers(address: str, *, since: datetime | None = None, until: datetime | None = None, limit: int | None = None, cursor: str | None = None) -> AsyncIterator[Transfer]
```

The movements involving one address, newest first.

**Both native and token movements, in one stream.** This is the sample a coincidence rate
is counted over, and the count it is contrasted with — the transfer checker's ``k`` —
counts a native value transfer *plus one movement per token log*. A rate drawn only from
native movements would price a different population from the ``k`` it is set against, which
would be a comparison between two numbers that are not about the same thing.

The two endpoints are walked in turn rather than interleaved: each is already newest-first,
and a caller is counting a rate over a sample, not reading a timeline. Merging them into one
order would cost a sort over pages that have not been fetched.

**The bound is by block, not by time.** Etherscan's ``txlist`` takes ``startblock`` and
``endblock`` and has no time range, so a ``since`` stops the walk early — the order is
descending, so everything past the first movement older than the bound is older still — and
cannot be pushed down to the provider. That is why a caller sampling the *outside* of a
window pays for every page between now and the window's start, exactly as
`EsploraProvider.get_window_transfers` does.

**A heavy address is capped by Etherscan, silently.** The free tier returns at most the
10,000 most recent records for these endpoints and does not say so in the response; the walk
simply ends. That is the same gap Esplora documents — "the provider cannot know whether the
history was exhausted" — and it is worse here only because a plausible-looking answer comes
back rather than a short one. A caller that needs to know must count what it got.

**Raises**

- `ConfigurationError` — the API key is missing or rejected.
- `RateLimitError` — the quota is exhausted.

### `aclose`

```python
aclose() -> None
```
