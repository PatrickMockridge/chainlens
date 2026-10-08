# `chainlens.ledger.schema`

The wire contract for a ledger document, and the one guarantee it has to keep.

The pydantic models are the only hand-maintained description of the format. Everything
else is generated from them: the JSON Schema that a front end reads, and the golden
fixture the TypeScript side validates against. That is deliberate — two hand-maintained
descriptions of one format drift, and the drift is invisible until a field renders as
``undefined`` in a browser.

Two things this module exists to guarantee, both of which are cheap here and expensive
later:

**Nothing non-finite reaches the wire.** JSON has no ``Infinity`` or ``NaN``, and there
are two ways one escapes Python. ``json.dumps`` writes the token and Python parses it
back, so it survives here and breaks in a browser. Pydantic is quieter: it writes
``null``, so a field whose *meaning* was infinity comes back as "no value" — valid JSON,
silently different. `strict_dumps` catches both, and the second is the one that
matters, because a likelihood ratio in this library can legitimately be infinite.

**A field that exists is a field the contract describes.** `document_schema` is
emitted from the models, and the committed copy is compared against a fresh render by a
test — so adding a field without regenerating is a red build rather than a silent
addition the front end never sees.

## `DOCUMENTS`

## `SCHEMA_DIR`

## `document_schema`

```python
document_schema(name: str) -> dict[str, Any]
```

The JSON Schema for one of the documents, straight from its model.

``mode="serialization"``, because a front end reads what this library *emits* rather than
what it accepts. The two differ wherever a field has a serializer — a base-unit amount is
an ``int`` in Python and a decimal string on the wire — and generating the validation schema
would tell a TypeScript consumer to expect an integer that never arrives.

**Raises**

- `KeyError` — the name is not a document this module knows. Named rather than swallowed, because a silently empty schema is a front end validating against nothing.

## `render_schemas`

```python
render_schemas() -> dict[str, str]
```

Every schema, formatted for committing.

One file per document rather than one file holding both: a code generator emits a module
per file, and a single file with two roots would need a hand-written entry point that
nobody would remember to extend when a third document appears.

Sorted keys, so a diff shows the change rather than the key ordering.

## `schema_path`

```python
schema_path(name: str) -> Path
```

Where the committed schema for ``name`` lives.

## `strict_dumps`

```python
strict_dumps(document: BaseModel) -> str
```

Serialise a document to JSON that a strict parser anywhere will accept.

Two guarantees, because there are two ways a non-finite float escapes a Python
process and only one of them is visible in the output:

* **Pydantic writes ``null``.** A field whose *meaning* was infinity becomes "no
  value" — valid JSON, silently different. That is the dangerous one, and it is why
  the object is walked rather than the text.
* **``json.dumps`` writes ``Infinity``.** Python parses it back, so it survives a
  round trip here and breaks in a browser. The emitted text is therefore re-parsed
  with a parser configured to refuse it.

A likelihood ratio in this library can legitimately be infinite — the coincidence
probability can be exactly zero — so the wire model has to represent that case as a
flag beside a null rather than as a number. This function is what makes that a
requirement rather than a good intention.

**Raises**

- `ValueError` — the document holds a non-finite float, or would not survive a strict JSON parser. Either is a defect in the document rather than in the caller.

## `strict_json`

```python
strict_json(value: Any, *, indent: int | None = None) -> str
```

Serialise a plain structure — not a model — as JSON a strict parser will accept.

The same guarantee `strict_dumps` gives a document, for the exporters that build their
payload from ordinary dictionaries and lists. ``graph/export.py`` is the one that does, and it
borrows this rather than growing a second copy of the discipline.

``allow_nan=False`` is what refuses an infinity at the point of writing; the walk is what names
the field, because ``json``'s own complaint ("Out of range float values are not JSON
compliant") does not tell a caller *which* value it was, and an exporter's caller is usually a
person looking at a graph they cannot search.

**Raises**

- `ValueError` — the value holds a non-finite float.
