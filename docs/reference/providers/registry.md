# `chainlens.providers.registry`

Provider discovery and lookup.

Two mechanisms, deliberately both:

* **Entry points** (``importlib.metadata``, group ``chainlens.providers``) are the
  only zero-config way for a third party to ship a provider. Their package
  declares the entry point, and ``pip install`` is the entire integration step.
* **Explicit registration** is not optional, because entry-point scanning is
  process-global and unordered. It cannot express a *configured instance* (a
  provider with an API key and a distinct name), and it makes test isolation
  impossible.

Entry points are loaded **lazily** -- the ``EntryPoint`` is stored, the module is
imported on first use. A third-party plugin with a syntax error therefore cannot
break ``import chainlens``; it fails when someone asks for it, and the failure is
recorded in `ProviderRegistry.load_errors` rather than raised at import.

## `ProviderInfo`

A summary of a provider known to the registry.

**Members**

- `name`
- `chain` = None
- `capabilities` = Field(default_factory=frozenset)
- `redistributable` = False
- `location` = None

## `ProviderRegistry`

```python
ProviderRegistry(*, discover: bool = True, settings: Settings | None = None)
```

A resolvable set of providers.

Not a singleton by construction: tests build their own with
``discover=False``, which yields a registry containing **only** what is
registered explicitly — no built-ins and no third-party entry points — so an
assertion cannot be influenced by the ambient environment.

### `register`

```python
register(key: str, provider: type[Any] | Provider, *, override: bool = False) -> None
```

Register a provider class or configured instance under ``key``.

**Parameters**

- `key` `str` — the name it will be looked up by.
- `provider` `type[Any] | Provider` — a class (instantiated on first use) or an instance.
- `override` `bool`, default `False` — replace an existing registration instead of raising.

**Raises**

- `ValueError` — if ``key`` is taken and ``override`` is false, or the object does not look like a provider.

### `unregister`

```python
unregister(key: str) -> None
```

Remove a provider. No-op if it was never registered.

### `keys`

```python
keys() -> tuple[str, ...]
```

Every registered key, from any mechanism, sorted.

### `get`

```python
get(key: str, **kwargs: Any) -> Provider
```

Resolve a provider by key, instantiating and caching it on first use.

**Raises**

- `ProviderError` — if no provider is registered under ``key``.
- `PluginLoadError` — if a registered plugin could not be imported.

### `discover`

```python
discover(*, refresh: bool = False) -> tuple[str, ...]
```

Load the set of entry points advertising providers.

Returns the entry-point names. Discovery never imports a plugin, so a
broken third party cannot break this call.

### `available`

```python
available(*, chain: Chain | None = None, require: Iterable[Capability] = ()) -> Mapping[str, ProviderInfo]
```

Providers matching a chain and capability filter.

Providers that fail to load are skipped and recorded in
`load_errors` rather than aborting the listing. A provider missing
its credentials is skipped too: one unconfigured provider must not make it
impossible to ask what else is available.

### `default_for`

```python
default_for(chain: Chain, capability: Capability) -> Provider
```

The preferred provider for a chain and capability.

Preference follows `_DEFAULT_PREFERENCE` (free providers first),
then alphabetical order.

**Raises**

- `ProviderError` — if nothing can serve the request.

### `load_errors`

Plugin load failures seen so far, in order. Never raised by discovery.

## `PROVIDER_ENTRY_POINT_GROUP`

## `get_registry`

```python
get_registry() -> ProviderRegistry
```

The process-wide registry, with discovery enabled.

## `reset_registry_cache`

```python
reset_registry_cache() -> None
```

Clear the process-wide registry. For tests that mutate the environment.
