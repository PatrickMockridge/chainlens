# `chainlens.testing.in_memory`

A provider backed by plain Python data.

This is **public API**, not a test helper in disguise. Two reasons it ships in the
package rather than under ``tests/``:

1. A third-party plugin author needs a provider to test *their* analysis code
   against without standing up HTTP fixtures.
2. It is what makes the analysis layer testable at all. Clustering, tracing, graph
   building and reporting are the highest-risk logic in the library, and with this
   provider they are tested with **no network, no cassettes, and no I/O** -- in
   milliseconds.

It advertises only what its fixture data can actually serve, so a caller that asks for
``METRICS``, ``SQL_QUERY`` or ``LABELS`` gets a
`chainlens.exceptions.CapabilityError` rather than a silent empty result. That
asymmetry is worth testing, and it is why a capability is declared by decorating the
method that implements it rather than by listing it by hand.

## `InMemoryProvider`

```python
InMemoryProvider(*, chain: Chain = Chain.BITCOIN, name: str | None = None, transactions: Iterable[Transaction] = (), addresses: Iterable[Address] = (), blocks: Iterable[Block] = (), token_transfers: Iterable[Transfer] = (), settings: Settings | None = None, latency: float = 0.0, fail_with: Mapping[str, BaseException] | None = None)
```

Serves addresses, transactions, blocks and balances from supplied objects.

**Parameters**

- `chain` `Chain`, default `Chain.BITCOIN` — which chain the fixture data represents.
- `name` `str | None`, default `None` — overrides the provider name, to tell two of these apart.
- `transactions` `Iterable[Transaction]`, default `()` — the transactions this provider knows about.
- `addresses` `Iterable[Address]`, default `()` — optional pre-built address summaries. A missing address is synthesized from the transactions that reference it.
- `blocks` `Iterable[Block]`, default `()` — optional block headers.
- `token_transfers` `Iterable[Transfer]`, default `()` — token movements to serve. Each is returned for **both** of its addresses, the way a real index does, so a caller that walks both sides sees it twice and has to dedupe by its own key — which is the bug a fixture that served it once would hide.
- `latency` `float`, default `0.0` — seconds to ``await`` before every call. Useful for exercising concurrency and rate-limit behaviour.
- `fail_with` `Mapping[str, BaseException] | None`, default `None` — maps a method name (e.g. ``"get_transaction"``) to the exception that call should raise. For testing error paths.

**Members**

- `name` = 'in-memory'
- `redistributable` = True
- `chain` = chain
- `capabilities` = self.capabilities - {Capability.TOKEN_TRANSFERS}

### `from_fixture`

```python
from_fixture(path: str | Path, **kwargs: Any) -> Self
```

Build a provider from a JSON fixture file.

The file is an object with optional ``chain``, ``transactions``,
``addresses`` and ``blocks`` keys, each holding serialized models.

### `get_address`

```python
get_address(address: str) -> Address
```

### `get_address_transactions`

```python
get_address_transactions(address: str, *, limit: int | None = None, cursor: str | None = None, since: datetime | None = None, until: datetime | None = None) -> AsyncIterator[Transaction]
```

### `get_window_transfers`

```python
get_window_transfers(address: str, *, since: datetime | None = None, until: datetime | None = None, limit: int | None = None, cursor: str | None = None) -> AsyncIterator[Transfer]
```

The movements involving one address, read from what the fixtures recorded.

A movement is derived here exactly as a real provider's would be: on a UTXO chain from
the recorded outputs paying the address and inputs spending from it, on an account chain
from the transaction's own sender and recipient. Nothing is apportioned — a share of a
co-funded output belongs to the *coin-selection* question, not to what moved.

A transfer in ``token_transfers`` appears for both of its addresses, the way a real index
returns it, so a caller that walks both sides sees it twice and has to dedupe by its own
key — the bug a fixture that served it once would hide.

### `get_transaction`

```python
get_transaction(txid: str) -> Transaction
```

### `get_block`

```python
get_block(reference: str | int) -> Block
```

### `get_balance`

```python
get_balance(address: str) -> Balance
```

### `get_token_transfers`

```python
get_token_transfers(address: str, *, limit: int | None = None, cursor: str | None = None) -> AsyncIterator[Transfer]
```

Yield the token movements this address takes part in.

A movement is returned for **each** of its endpoints, the way a real index does,
so a caller that walks both sides of a transfer sees it twice and has to dedupe
by its own key. Serving it once would make the walk look correct while hiding the
deduplication bug it will hit against a live provider.
