# `chainlens.report.builder`

Assemble a defensible investigation report from analysis results.

The point of this module is not formatting. It is that **a report which cannot be
checked is not a report**, so two sections are mandatory and structurally
enforced rather than optional extras a caller might forget:

* **Methodology** — what was done, with which tool, under which limits.
* **Provenance** — where every fact came from, deduplicated and listed.

A report that cites chain data while recording no provenance fails to construct.
That is a `ValueError` at build time rather than a quiet omission in a PDF, because
the failure mode it prevents is a document that looks authoritative and cannot be
audited.

## `FlowRow`

One value movement, flattened for tabular rendering.

``txids`` is carried into the table rather than summarised away: an amount a
reader cannot trace back to a transaction is an assertion, not evidence.

**Members**

- `src`
- `dst`
- `amount` = Field(ge=0)
- `amount_label`
- `asset_kind`
- `hops` = Field(ge=0)
- `n_transfers` = Field(ge=1)
- `txids` = ()
- `confidence` = Field(ge=0.0, le=1.0)
- `apportioned` = False
- `is_change` = False

## `InvestigationReport`

A complete, renderable report.

**Attributes**

- `title` `str` — what this report is about.
- `chain` `Chain` — the chain analysed.
- `seed` `str` — the address the trace started from.
- `created_at` `datetime` — when it was assembled.
- `graph` `FlowGraph | None` — the traced value-flow graph, if a trace was run.
- `entities` `tuple[Entity, ...]` — clusters found, with their evidence.
- `observations` `tuple[Label, ...]` — labels produced by heuristics rather than merges.
- `summary` `GraphSummary | None` — structural metrics over the graph.
- `refusals` `tuple[Refusal, ...]` — merges a declared non-equivalence forbade.
- `warnings` `tuple[str, ...]` — anything that truncated or degraded the analysis.
- `provenance` `tuple[Provenance, ...]` — every source consulted, deduplicated.
- `redistributable` `bool` — whether the sources permit redistributing this content.
- `methodology` `str` — how the analysis was performed. Must not be empty.
- `limitations` `str` — what the output does and does not support. Must not be empty.

**Members**

- `title`
- `chain`
- `seed`
- `created_at`
- `graph` = None
- `entities` = ()
- `observations` = ()
- `summary` = None
- `refusals` = ()
- `warnings` = ()
- `provenance` = ()
- `redistributable` = False
- `methodology` = STANDARD_METHODOLOGY
- `limitations` = STANDARD_LIMITATIONS

### `truncated`

Whether the underlying trace stopped early.

### `flows`

Edges, largest first, then by key so the order is stable.

### `flow_rows`

```python
flow_rows() -> tuple[FlowRow, ...]
```

Flattened edges, ready for a table.

### `apportioned_flow_count`

```python
apportioned_flow_count() -> int
```

How many edges rest on an apportioned rather than recorded split.

### `activity_window`

Earliest and latest timestamps seen on any edge, if the provider supplied them.

``None`` for both when no edge carried a timestamp, which is common on
providers that omit block times. Reported as unknown rather than as the
report's own generation time.

### `labelled_entities`

```python
labelled_entities() -> tuple[Entity, ...]
```

Entities carrying at least one label -- the ones an analyst cares about.

### `all_txids`

```python
all_txids() -> tuple[str, ...]
```

Every transaction id cited anywhere in the report, sorted and deduplicated.

### `provenance_keys`

```python
provenance_keys() -> tuple[str, ...]
```

Each source rendered as a short line for the provenance table.

## `ReportBuilder`

```python
ReportBuilder(*, title: str | None = None, methodology: str | None = None, limitations: str | None = None, redistributable: bool = False)
```

Collects analysis results and assembles a report.

**Parameters**

- `title` `str | None`, default `None` — overrides the derived title.
- `methodology` `str | None`, default `None` — overrides the standard text. Passing an empty string is rejected at build time -- the field exists so a caller can be *more* specific, not to allow omitting it.
- `limitations` `str | None`, default `None` — as above.
- `redistributable` `bool`, default `False` — whether the sources permit redistributing this content. Defaults to ``False``, the cautious answer, because assuming otherwise is the mistake with legal consequences.

### `build`

```python
build(*, chain: Chain, seed: str, graph: FlowGraph | None = None, cluster_result: ClusterResult | None = None, summary: GraphSummary | None = None, entities: Sequence[Entity] = (), observations: Iterable[Label] = (), refusals: Iterable[Refusal] = (), warnings: Iterable[str] = ()) -> InvestigationReport
```

Assemble a report, collecting provenance from everything supplied.

## `STANDARD_LIMITATIONS`

## `STANDARD_METHODOLOGY`
