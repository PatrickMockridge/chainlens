# `chainlens.models.annotate`

Evidence placed on a graph, and the annotations a person adds.

Two things live here because they meet: the *overlay* — what the analysis layers already
computed, joined onto the node and edge keys a graph uses — and the *annotation*, which is
evidence a person asserts and which the overlay carries alongside the rest.

The overlay is a join, never a source. It fetches nothing, infers nothing, and adds no fact
that was not already in a finding, a label, a cluster or an annotation. So a reader who
disagrees with something on a node can follow it back to whatever produced it rather than
taking the graph's word for it.

**An annotation is kept structurally apart from computed evidence, not stylistically.** It
lives in its own collection, carries `LabelSource.USER`, and the model has no field capable
of holding a number, a verdict or a confidence: a person may assert *what* an address is and
never *how sure* the library should be. `Label` is reused only as a rendering projection, so
a declared label appears in the same rail as a provider's while still saying whose assertion
it is. The distinction has to survive a screenshot and a JSON export, and the surest way to
guarantee that is for the wrong thing to be unrepresentable.

## `Annotation`

Evidence a person asserts about a node or an edge.

**Attributes**

- `schema_version` `int` — the contract version.
- `id` `str` — content-addressed.
- `created_at` `AwareDatetime` — when it was recorded. Always timezone-aware.
- `author` `str` — who asserted it. **Required**, with no default: an assertion has an owner.
- `basis` `str` — why they say so. **Required**, for the same reason the case study refuses a claim record with no falsifier — an assertion with no stated ground is not a record, it is an opinion with a timestamp.
- `target` `GraphRef` — what it is about, named the way a graph names it.
- `kind` `AnnotationKind` — which kind of assertion it is.
- `assertion` `str` — the claim in the author's own words, kept verbatim.
- `evidence_urls` `tuple[str, ...]` — anything a reader can go and look at.
- `source` `LabelSource` — always ``USER``. Carried rather than assumed, so a renderer distinguishes a declared label from a provider's without having to know where it came from.

**Members**

- `schema_version` = 1
- `id`
- `created_at`
- `author` = Field(min_length=1)
- `basis` = Field(min_length=1)
- `target`
- `kind`
- `assertion` = Field(min_length=1)
- `evidence_urls` = ()
- `source` = LabelSource.USER

### `create`

```python
create(*, target: GraphRef, kind: AnnotationKind, assertion: str, author: str, basis: str, created_at: datetime, evidence_urls: tuple[str, ...] = ()) -> Annotation
```

Build an annotation, deriving its identifier from its content.

## `AnnotationKind`

What a person is asserting about a target.

Deliberately a short vocabulary of *kinds of assertion* rather than free text. A kind
can be checked against a computed label — and a disagreement between the two is worth
showing — whereas a sentence cannot.

**Members**

- `EXCHANGE` = 'exchange'
- `MIXER` = 'mixer'
- `SANCTIONED` = 'sanctioned'
- `OWN_WALLET` = 'own_wallet'
- `CORRECTION` = 'correction'
- `NOTE` = 'note'

## `AnnotationRequest`

What a client sends to record an annotation.

The *request* rather than the record, because two fields of the record are not the
client's to supply. ``id`` is content-addressed and derived by the same function whatever
wrote it, so two clients recording the same assertion agree; ``created_at`` is stamped by
whoever accepts the record, because a browser's clock is not an authority and a record
committed to a repository should say when it *was* recorded rather than when a machine
believed it was.

There is deliberately no ``source`` field. ``Annotation`` refuses to claim anything but
``USER``, and leaving the field out means an attempt to record provider evidence through
this path is rejected as an unknown field rather than as a value that failed a check —
the failure is at the shape, which cannot be worked around.

The constraints ``Annotation`` enforces (an owner, a stated basis, a source that is the
person's own) are enforced there, once. This model only fixes the field set.

**Members**

- `target`
- `kind`
- `assertion`
- `author`
- `basis`
- `evidence_urls` = ()

## `EvidenceItem`

One thing known about a node or an edge.

**Attributes**

- `kind` `EvidenceKind` — where it came from.
- `summary` `str` — a sentence for a reader.
- `detail` `tuple[DetailEntry, ...]` — labelled facts in the tagged form a second language can render.
- `claim_id` `str | None` — the claim this belongs to, when it came from a finding, so the graph and a derivation can highlight each other.
- `graph_refs` `tuple[GraphRef, ...]` — everything this item touches, with ``exists`` resolved against the document it was joined onto.
- `provenance` `tuple[Provenance, ...]` — where the fact came from, when a provider supplied it.
- `source` `LabelSource | None` — whose assertion it is, when it is a label of any kind.
- `confidence` `float | None` — only ever a *heuristic's* own confidence, never a declared one — see the annotation model, which has no such field.

**Members**

- `kind`
- `summary`
- `detail` = ()
- `claim_id` = None
- `graph_refs` = ()
- `provenance` = ()
- `source` = None
- `confidence` = Field(default=None, ge=0.0, le=1.0)

## `EvidenceKind`

Where a piece of evidence came from.

The first four are computed by the library and the last is asserted by a person, and
they are separate members so a renderer cannot accidentally style them alike.

**Members**

- `FINDING` = 'finding'
- `LABEL` = 'label'
- `ENTITY` = 'entity'
- `WARNING` = 'warning'
- `ANNOTATION` = 'annotation'

## `EvidenceOverlay`

Everything known about a graph's nodes and edges, keyed the way the graph is.

**Attributes**

- `schema_version` `int` — the contract version.
- `by_node` `Mapping[str, tuple[EvidenceItem, ...]]` — node key to the evidence about it, in a stable order.
- `by_edge` `Mapping[str, tuple[EvidenceItem, ...]]` — edge key to the evidence about it.
- `claim_refs` `Mapping[str, tuple[GraphRef, ...]]` — claim id to everything that claim touches, so selecting a claim in one view can highlight it in the other.
- `unjoined` `tuple[GraphRef, ...]` — references that resolved to nothing here. **Reported, never dropped**: a claim about an address outside the walked window would otherwise vanish, and "we hold evidence about something you cannot see — deepen the walk" is both true and actionable.
- `warnings` `tuple[str, ...]` — anything that qualified the join.

**Members**

- `schema_version` = 1
- `by_node` = Field(default_factory=dict)
- `by_edge` = Field(default_factory=dict)
- `claim_refs` = Field(default_factory=dict)
- `unjoined` = ()
- `warnings` = ()

### `item_count`

How many items the overlay holds, counting one per node or edge it lands on.

### `covered_keys`

Every node and edge key carrying at least one item, in a stable order.

### `unresolved_count`

How many references pointed at something this document does not hold.

### `has_annotations`

Whether any evidence here was asserted by a person rather than computed.

## `FORBIDDEN_ANNOTATION_FIELDS`

## `annotation_id`

```python
annotation_id(*, target: GraphRef, kind: AnnotationKind, assertion: str, author: str) -> str
```

A content-addressed identifier for an annotation.

Content-addressed so re-recording the same assertion is idempotent and a *changed*
assertion is visibly a different record rather than the same one edited — which matters
because these are committed, and a reader has to be able to tell an amendment from a
silent rewrite.
