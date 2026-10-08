# `chainlens.providers.capabilities`

Capability declarations.

A provider is asked to declare what it can actually do, and the declaration is
*derived from its code* rather than written by hand. That is the point of the
``@provides`` decorator: a hand-maintained ``capabilities`` set drifts from the
methods that exist, and the failure mode is a tracer that dispatches to a method
which raises halfway through an investigation.

A capability set is therefore collected from the decorated methods on a class,
walked across the MRO. A subclass may still override the set explicitly by
assigning ``capabilities`` in its own body, which is the escape hatch for a
provider that wants to *withhold* something it inherited.

Underneath, this is **one decorator factory and several vocabularies**:
`make_provides` takes the attribute name a declaration is recorded onto, and
`provides` is that factory bound to this module's name. A second vocabulary
therefore costs an enum and an attribute name rather than a second mechanism —
and it gets its *own* attribute, so two vocabularies on one class stay disjoint.

## `Capability`

A discrete thing a provider can be asked to do.

The values are dotted namespaces so they group visually and sort sensibly in
error messages.

**Members**

- `ADDRESS` = 'address'
- `ADDRESS_TXS` = 'address.txs'
- `ADDRESS_UTXO` = 'address.utxo'
- `TX` = 'tx'
- `BLOCK` = 'block'
- `BALANCE` = 'balance'
- `TOKEN_TRANSFERS` = 'token.transfers'
- `LOGS` = 'logs'
- `INTERNAL_TXS` = 'internal.transfers'
- `WINDOW_TRANSFERS` = 'address.transfers'
- `METRICS` = 'metrics'
- `SQL_QUERY` = 'query.sql'
- `LABELS` = 'labels'

## `ADDRESS_CAPABILITIES`

## `E`

## `F`

## `LABEL_CAPABILITIES`

## `METRICS_CAPABILITIES`

## `QUERY_CAPABILITIES`

## `collect_capabilities`

```python
collect_capabilities(cls: type[Any]) -> frozenset[Capability]
```

Union the capabilities declared by every method across ``cls``'s MRO.

## `collect_declared`

```python
collect_declared(cls: type[Any], attr: str) -> frozenset[StrEnum]
```

Union what a class's MRO declares under ``attr``.

Deliberately returns the bare base type rather than a type parameter: a type
parameter here could never be inferred from the arguments, so every caller
would have to annotate the result to say what the *name* already said. The
narrowing belongs where the name is chosen, which is the one place that knows.

## `declared_by`

```python
declared_by(member: object, attr: str = _PROVIDES_ATTR) -> frozenset[StrEnum]
```

The declarations a single class member makes under ``attr``, if any.

## `make_provides`

```python
make_provides(attr: str) -> _Declarer
```

Build a ``@provides``-style decorator that records onto ``attr``.

Each vocabulary gets its **own attribute name**, and that separation is the
point. Chain providers declare `Capability`; the social layer declares
its own enum. Merged onto one attribute, a class that is both a chain provider
and a post source would union two unrelated declarations across its MRO, and a
capability would appear to exist because a method of the same name was
decorated for an entirely different reason.

**Parameters**

- `attr` `str` — the attribute name the declaration is stored under. The name *is* the vocabulary — two decorators sharing one name share one set.

## `provides`

```python
provides(*capabilities: Capability) -> Callable[[F], F]
```

Declare that a method implements the given capabilities.

Multiple decorators compose; the sets are unioned.
