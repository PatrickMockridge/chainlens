# `chainlens.ledger.annotate`

Joining what is known onto the graph, and reporting what does not fit.

A pure function over things the other layers already computed. It fetches nothing, infers
nothing, and the only thing it decides is *where* each fact belongs — which node or edge it
is about — plus whether that node or edge is actually here.

That last part is the reason this module exists rather than the join living in a renderer.
Evidence about a node the document does not hold is a real and common situation: a claim
naming an address outside the walked window, a label for a counterparty one hop further out,
a cluster member nobody expanded. Dropping it would make the graph look complete, so it goes
into `chainlens.models.annotate.EvidenceOverlay.unjoined` instead, carrying the key
that would resolve it — and the reader is told to deepen the walk rather than shown nothing.

An annotation lands the same way as anything else, and is the only item that carries
``LabelSource.USER``. Nothing here treats it differently from computed evidence in *joining*
it; the difference is in what it can say, which its model enforces.

## `overlay`

```python
overlay(graph: LedgerGraph, *, findings: Sequence[VerificationFinding] = (), labels: Mapping[str, tuple[Label, ...]] | None = None, entities: Sequence[Entity] = (), annotations: Sequence[Annotation] = (), warnings: Sequence[str] = ()) -> EvidenceOverlay
```

Join everything known onto a graph's own keys.

**Parameters**

- `graph` `LedgerGraph` — the document being joined onto. Its keys are the vocabulary; nothing here invents one.
- `findings` `Sequence[VerificationFinding]`, default `()` — verification findings. Each becomes one item naming every key it touches, and its references are resolved here.
- `labels` `Mapping[str, tuple[Label, ...]] | None`, default `None` — attribution labels **keyed by address**, which is authoritative — a label object may not carry its own address, and the caller joining them already knows which address it looked up.
- `entities` `Sequence[Entity]`, default `()` — clusters, whose members are joined to address nodes. A cluster is evidence *about* its members rather than a node of its own, because this view never merges addresses into an entity: the merge is a hypothesis, and hiding the addresses would hide the thing a reader came to look at.
- `annotations` `Sequence[Annotation]`, default `()` — assertions by a person. Joined exactly like anything else; what they can *say* is constrained by their model, not by this function.
- `warnings` `Sequence[str]`, default `()` — anything the caller knows about the join's inputs.

**Returns**

- `` `EvidenceOverlay` — The overlay, with every reference either placed or reported as unjoined.

## `stamp`

```python
stamp(graph: LedgerGraph, *, annotations: Sequence[Annotation]) -> LedgerGraph
```

A copy of ``graph`` carrying ``annotations``, with their ids on the nodes and edges.

What an *export* needs and a served document does not. A served graph joins the same records
through `overlay`, which produces one item per fact for a renderer; an exported file has
no server behind it, so it carries the records themselves (``LedgerGraph.annotations``) and
the ids that say which nodes and edges they are about.

**The ids are the only thing that touches ``nodes`` and ``edges``.** An annotation is never
merged into them: a node that carried an assertion's text would be indistinguishable, in a
JSON export, from a node the ledger recorded. The walk cannot do this itself — it has no
annotation store and should not grow one — which is why it happens at the point the store is
known.

An annotation whose target is not in the document still appears in the collection: the same
rule as the overlay's ``unjoined``. It is kept on the document even when it points at nothing,
rather than dropped, so a reader can see that something *was* asserted about a node this
export does not hold.
