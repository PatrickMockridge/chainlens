# `chainlens.providers.composite`

Compose several providers into one that answers everything any of them can.

The motivating case is Ethereum. A public JSON-RPC node can say what a transaction
was and what an address holds, but it keeps no index and so cannot list an
address's transactions. Etherscan can. Neither alone covers the ground; together
they do, and the caller should not have to know which is which:

    client.eth     # a CompositeProvider over [EtherscanProvider, JsonRpcEthProvider]

Routing is by capability and by declared order, so the first provider that claims a
capability answers for it. Order therefore encodes preference, and it is the
caller's to set -- free before paid, local before remote, whichever is trusted for
the question at hand.

## `CompositeProvider`

```python
CompositeProvider(providers: Sequence[Provider], *, chain: Chain | None = None, settings: Settings | None = None, name: str | None = None)
```

Fan-out that answers each capability with the first provider that has it.

**Parameters**

- `providers` `Sequence[Provider]` — in preference order. The first that advertises a capability serves every request for it.
- `chain` `Chain | None`, default `None` — the reported chain. Defaults to the first provider's, and a composite of providers on different chains is rejected.

**Members**

- `chain` = chain if chain is not None else next(iter(chains))
- `name` = name or 'composite(' + ','.join(p.name for p in self._providers) + ')'
- `capabilities` = frozenset(capabilities)
- `redistributable` = all(bool(getattr(provider, 'redistributable', False)) for provider in self._providers)

### `providers`

The sub-providers, in routing order.

### `provider_for`

```python
provider_for(capability: Capability) -> Provider
```

The sub-provider that will answer ``capability``.

**Raises**

- `CapabilityError` — if no sub-provider advertises it.

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

### `get_metrics`

```python
get_metrics(metric: str, *, asset: str, since: datetime | None = None, until: datetime | None = None, interval: str = '24h') -> Sequence[MetricPoint]
```

### `run_query`

```python
run_query(query: str, *, params: Mapping[str, Any] | None = None, limit: int | None = None) -> tuple[Mapping[str, Any], ...]
```

### `get_labels`

```python
get_labels(addresses: Sequence[str]) -> Mapping[str, tuple[Label, ...]]
```

### `aclose`

```python
aclose() -> None
```

Close every sub-provider, so one teardown releases all connections.
