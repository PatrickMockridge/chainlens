# `chainlens.analysis.heuristics.base`

The heuristic contract and its registry.

Heuristics are the part of this library most able to mislead, so the contract
leans on one rule: **a heuristic that is not sure should abstain**. Producing no
merge is always an acceptable outcome; producing a confident wrong merge is not.
Where a heuristic can express partial belief it does so through a confidence in
``[0, 1]`` and leaves the decision to the caller's threshold.

Heuristics declare which ledger models they apply to rather than which chains, so
a new UTXO chain gets Bitcoin's heuristics automatically instead of needing a new
entry in every list.

Discovery mirrors the provider registry: built-ins are registered from code (so a
source checkout works) and third-party heuristics arrive via the
``chainlens.heuristics`` entry point group, loaded lazily so a broken plugin
cannot break a run.

## `Heuristic`

One clustering rule.

Subclasses set ``name``, optionally ``version`` and the ledger models they
apply to, and implement `run`.

**Members**

- `name` = 'unnamed'
- `version` = '1'
- `chain_models` = frozenset()
- `required_capabilities` = frozenset()

### `applicable`

```python
applicable(context: HeuristicContext) -> bool
```

Whether this heuristic can reason about the given context.

### `run`

```python
run(context: HeuristicContext) -> HeuristicResult
```

Produce merges, labels and change flags.

Must not raise for surprising input: a heuristic that cannot proceed
returns an empty result with a warning, so one weak rule cannot abort a
whole run.

## `HeuristicContext`

```python
HeuristicContext(chain: Chain, transactions: tuple[Transaction, ...] = (), addresses: frozenset[str] = frozenset(), labels: Mapping[str, tuple[Label, ...]] = dict())
```

The material a heuristic reasons over.

Deliberately just data: a heuristic has no provider access, so it cannot
quietly make network calls and cannot be non-deterministic. Whatever the
engine fetched is what the heuristic sees.

**Members**

- `chain`
- `transactions` = ()
- `addresses` = frozenset()
- `labels` = field(default_factory=dict)

### `by_id`

```python
by_id() -> dict[str, Transaction]
```

Transactions keyed by txid.

### `transactions_touching`

```python
transactions_touching(address: str) -> tuple[Transaction, ...]
```

Transactions in which ``address`` appears on either side.

## `HeuristicRegistry`

```python
HeuristicRegistry(*, builtins: bool = True, discover: bool = True)
```

A resolvable set of heuristics.

**Parameters**

- `builtins` `bool`, default `True` — seed with the in-tree heuristics.
- `discover` `bool`, default `True` — also read the ``chainlens.heuristics`` entry points. Tests pass ``False`` to get a registry containing only what they registered.

**Members**

- `load_errors`

### `register`

```python
register(heuristic: Heuristic | type[Heuristic], *, key: str | None = None, override: bool = False) -> str
```

Register a heuristic instance or class under its name.

### `unregister`

```python
unregister(name: str) -> None
```

Remove a heuristic. No-op if it was never registered.

### `discover`

```python
discover(*, refresh: bool = False) -> tuple[str, ...]
```

Read the entry points advertising heuristics.

Returns their names. Never imports anything, so a broken third-party
plugin cannot break this call.

### `keys`

```python
keys() -> tuple[str, ...]
```

Every known heuristic name, from any mechanism.

### `get`

```python
get(name: str) -> Heuristic
```

Resolve a heuristic by name, importing a lazy one on first use.

**Raises**

- `KeyError` — if nothing is registered under that name.
- `PluginLoadError` — if a registered plugin could not be imported.

### `all`

```python
all() -> tuple[Heuristic, ...]
```

Every resolvable heuristic, sorted by name.

A heuristic that fails to load is skipped and recorded in
`load_errors`; one broken plugin must not stop a run.

### `for_chain`

```python
for_chain(chain: Chain) -> tuple[Heuristic, ...]
```

Heuristics whose declared ledger models include ``chain``'s.

## `HEURISTIC_ENTRY_POINT_GROUP`

## `get_heuristic_registry`

```python
get_heuristic_registry() -> HeuristicRegistry
```

The process-wide heuristic registry.
