# `chainlens.providers.base`

The provider contract and the recommended base class.

Two things live here:

* `Provider` -- a `typing.Protocol` describing the contract
  structurally. A third party can satisfy it by wrapping an existing SDK without
  importing our base class, which is deliberate: the whole point is that adding a
  provider should not require adopting our object model.
* `BaseProvider` -- an ABC that supplies capability bookkeeping, the
  fail-fast capability guard, and lane classification. A real adapter is then a
  few dozen lines of parsing.

Every method on the base raises `chainlens.exceptions.CapabilityError` for
a capability the provider does not advertise, and ``NotImplementedError`` if the
provider advertises it but forgot to implement it -- two very different bugs with
two very different fixes.

## `BaseProvider`

```python
BaseProvider(*, settings: Settings | None = None)
```

Convenience base implementing capability bookkeeping and lane helpers.

Subclasses should decorate each implemented method with ``@provides(...)``;
the advertised capability set is then collected automatically. Assigning
``capabilities`` explicitly in the subclass body overrides collection, which
is how a provider withholds something it inherited.

**Members**

- `name` = 'unnamed'
- `chain`
- `capabilities` = frozenset()
- `redistributable` = False

### `supports`

```python
supports(capability: Capability) -> bool
```

Whether this provider advertises ``capability``.

### `is_address_provider`

Whether this provider answers address-shaped questions.

### `is_metrics_provider`

Whether this provider serves network-level metrics only.

### `is_query_provider`

Whether this provider is query-shaped rather than address-shaped.

### `is_label_provider`

Whether this provider supplies attribution labels.

### `aclose`

```python
aclose() -> None
```

Release any held resources. The default is a no-op.

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

Movements involving one address, newest first, optionally within a range.

The range bounds are plain datetimes rather than a verification model: this layer sits
below `verify/`, and a protocol that took one of its types would invert the dependency.
Whether a boundary moment counts as inside the window is the claim's business.

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

## `Provider`

Structural contract for anything that can answer on-chain questions.

Implementations are not required to inherit from `BaseProvider`; they
only need these attributes and methods.

**Members**

- `name`
- `chain`
- `capabilities`
- `redistributable`

### `supports`

```python
supports(capability: Capability) -> bool
```

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
