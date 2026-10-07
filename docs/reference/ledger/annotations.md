# `chainlens.ledger.annotations`

Where declared annotations live: one JSON file per annotation, in a directory.

The format follows the case study's claim records — a directory of one-record-per-file JSON,
each carrying its own ``schema_version`` — and for the same reasons. A single file per record
diffs cleanly in git, never conflicts on a merge, and can be deleted by deleting a file.
The alternative, one growing array, turns every addition into a whole-file diff and every
concurrent edit into a conflict over the file rather than over the record.

JSON rather than TOML, which is the one place this differs from the case study. An
annotation's target and its provenance are nested models, and JSON is what pydantic
round-trips exactly; the case study's hand-rolled counterpart shows what it costs to parse a
nested model out of TOML by hand.

Nothing here decides whether an annotation is *true* or how much it is worth. The store is
about persistence, and the model is what constrains what may be asserted.

## `AnnotationStore`

```python
AnnotationStore(directory: Path)
```

A directory of annotation records.

**Parameters**

- `directory` `Path` — where the records live. Created on first write, not on construction — reading a directory that does not exist yet is an empty corpus rather than an error, because a first run has no annotations and that is not a failure.

### `directory`

Where the records live.

### `exists`

```python
exists() -> bool
```

Whether the directory has been created.

### `load`

```python
load() -> tuple[Annotation, ...]
```

Every record, oldest name first.

**Raises**

- `AnnotationStoreError` — a record is unreadable or does not validate. **Not** skipped: an annotation that cannot be read is a broken artifact, and quietly ignoring it would mean the graph renders a corpus with a hole nobody knows about. The message names the file.

### `append`

```python
append(annotation: Annotation) -> Annotation
```

Write one record, returning it.

Idempotent: the identifier is content-addressed, so recording the same assertion twice
writes the same file with the same bytes rather than accumulating duplicates.

### `extend`

```python
extend(annotations: Sequence[Annotation]) -> tuple[Annotation, ...]
```

Write several records.

## `AnnotationStoreError`

An annotation directory could not be read or written.
