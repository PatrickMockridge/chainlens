# `chainlens.adapters.esplora`

Esplora-based Bitcoin providers.

Esplora is the REST API served by Blockstream's explorer and by mempool.space.
Both expose the same schema at a different base URL, so one implementation covers
them: `chainlens.adapters.mempool_space.MempoolSpaceProvider` and
`chainlens.adapters.blockstream.BlockstreamProvider` are just base URLs
and names.

Schema quirks this module exists to absorb, each of which would otherwise corrupt
analysis downstream:

* ``vin[].value`` does not exist. An input's value lives at
  ``vin[].prevout.value``, and ``prevout`` is **null** for inputs whose previous
  output the instance has not indexed (common for young addresses). The value is
  therefore left ``None`` rather than defaulted to zero, because a zero would
  silently inflate every fee calculation.
* ``status.confirmed`` is the only reliable confirmation signal; a mempool
  transaction has no ``block_height``.
* ``scriptpubkey_type`` is a provider string that has changed spelling between
  versions (``p2wpkh`` and ``v0_p2wpkh`` both occur). It is mapped when
  recognised and otherwise derived locally from the output script.

## `EsploraProvider`

```python
EsploraProvider(*, base_url: str | None = None, chain: Chain | None = None, settings: Any = None, transport: Transport | None = None)
```

Bitcoin data over an Esplora-compatible REST API.

**Parameters**

- `base_url` `str | None`, default `None` — overrides the class default, e.g. to point at a testnet or self-hosted Esplora instance.
- `chain` `Chain | None`, default `None` — overrides the class default, for testnet variants.
- `transport` `Transport | None`, default `None` — an injected transport, used by tests.

**Members**

- `name` = 'esplora'
- `chain` = Chain.BITCOIN
- `base_url` = ''
- `redistributable` = True
- `rate_limit` = None

### `get_address`

```python
get_address(address: str) -> Address
```

### `get_balance`

```python
get_balance(address: str) -> Balance
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
get_address_transactions(address: str, *, limit: int | None = None, cursor: str | None = None, since: datetime | None = None, until: datetime | None = None) -> AsyncIterator[Transaction]
```

Yield an address's transactions, newest first.

Paging uses Esplora's ``/txs/chain/{last_txid}`` continuation. Because
confirmed transactions come back in descending block order, a ``since``
bound lets the walk stop early instead of paging through the entire
history of a busy address.

### `get_window_transfers`

```python
get_window_transfers(address: str, *, since: datetime | None = None, until: datetime | None = None, limit: int | None = None, cursor: str | None = None) -> AsyncIterator[Transfer]
```

The movements involving one address, newest first, from the transactions it appears in.

**Esplora has no ranged address scan**, so this is a bounded walk: page the address's
transactions newest-first and project each one. The consequences are stated rather than
discovered:

* **the cost is proportional to how far back the caller wants to look**, not to the size
  of the answer. A ``since`` bound stops the paging early, which is the only reason a busy
  address is affordable at all — a caller sampling the *outside* of a window has to page
  past it, and pays for every page in between.
* **a caller that asks for more than ``max_pages`` gets what the ceiling allowed** and is
  told, by the paging behaviour itself rather than by a silently short list: the iterator
  ends, and the provider cannot know whether the history was exhausted. Callers that need
  to know must count what they got.

Movements are read from the ledger's own fields: an output the address funded, and an
output that paid it. Nothing is apportioned — a share of a co-funded output belongs to the
coin-selection question, not to what moved.

### `aclose`

```python
aclose() -> None
```

## `mempool_space_rate_limit`

```python
mempool_space_rate_limit() -> RateLimit
```

The default budget for a free, unpublished Esplora instance.

mempool.space does not publish a limit and answers 429 when abused, so this
is a deliberately conservative courtesy rather than a documented figure.
