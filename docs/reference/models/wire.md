# `chainlens.models.wire`

Primitives shared by the documents a front end reads.

Two small things that both exist because a document crosses a language boundary, and
because the obvious encoding of each is subtly wrong on the far side.

`DetailEntry` replaces ``Mapping[str, Any]``. A checker writes whatever keys its
case needs — a balance writes ``observed_balance``, a transfer writes ``matching_transfers``
— and that free-form mapping is right on the Python side. Serialised to a browser it is
not: a Python dict's insertion order and a JavaScript object's are different things, so a
renderer keying off order produces a different list in each language; every value arrives
as ``unknown`` and needs narrowing by hand; and a nested object could carry something that
reads like a verdict. An ordered, tagged list fixes all three, and the coercion refuses a
type it does not recognise rather than guessing at one.

`GraphRef` is how one document points into another. A derivation branch names the
transactions and addresses it rests on, and those keys are resolved against a ledger
document that may not be the one loaded, or may not hold them at all. So a reference is
**carried whether or not it resolves** — the reader is told "there is more evidence here
that this view does not contain", which is a fact, rather than being shown a branch with
nothing under it.

## `DetailEntry`

One labelled fact, in a form two languages can render identically.

**Attributes**

- `key` `str` — the checker's own key, unchanged.
- `kind` `DetailKind` — which scalar this is, so a renderer needs no narrowing.
- `value` `str | int | float | bool | list[str] | None` — the value, or ``None`` when ``kind`` is ``null``.
- `unit` `str | None` — an optional unit for a number, e.g. ``"base units"``.

**Members**

- `key`
- `kind`
- `value` = None
- `unit` = None

## `DetailKind`

The six scalars a detail value can be.

Six, not "any": a value that is none of these is refused rather than stringified,
because stringifying is how a nested object becomes text that reads like a finding.

``INT`` carries its value as a **decimal string**, for the reason
`BaseUnits` sets out: a detail may be an amount, and an amount in a browser is a
double. A detail is free-form, so there is no field type to hang the rule on and it
belongs to the kind instead.

**Members**

- `STRING` = 'string'
- `INT` = 'int'
- `FLOAT` = 'float'
- `BOOL` = 'bool'
- `LIST` = 'list'
- `NULL` = 'null'

## `GraphRef`

A pointer into a ledger document, which may or may not hold it.

**Attributes**

- `kind` `GraphRefKind` — whether the reference names a node or an edge.
- `key` `str` — the node or edge key. Node keys are ``address:``/``tx:``/``unparsed:``; edge keys are ``{txid}:in|out|tok|int:{index}``.
- `exists` `bool | None` — whether it was found in the document it was resolved against. ``None`` means nobody has looked — which is not the same as absent, and a front end should offer to fetch rather than reporting nothing there.
- `note` `str | None` — why it was not found, when something knows.

**Members**

- `kind`
- `key`
- `exists` = None
- `note` = None

### `is_unresolved`

Whether this reference is known to point at nothing in the loaded document.

### `unresolved`

```python
unresolved(note: str) -> GraphRef
```

The same reference, marked as not present in the document it was checked against.

## `GraphRefKind`

What a reference points at. An edge is addressable here, unlike in the flow view.

**Members**

- `NODE` = 'node'
- `EDGE` = 'edge'

## `BaseUnits`

## `as_edge_ref`

```python
as_edge_ref(txid: str, index: int | None, role: str) -> GraphRef
```

An edge reference, spelled the way the ledger walk spells edge keys.

Kept here rather than in either module that needs it, because the spelling is a
contract between the derivation documents and the ledger document: if one changes and
the other does not, every reference silently stops resolving.

## `as_node_ref`

```python
as_node_ref(key: str) -> GraphRef
```

A node reference.

## `detail_entries`

```python
detail_entries(detail: Mapping[str, Any]) -> tuple[DetailEntry, ...]
```

Turn a checker's free-form mapping into an ordered, tagged list.

Sorted by key rather than left in insertion order: insertion order is a property of the
Python dict the checker happened to build, and a renderer that depended on it would
show the same facts in a different order in each language.

**Raises**

- `ValueError` — a value is not one of the six kinds.
