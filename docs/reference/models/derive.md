# `chainlens.models.derive`

The derivation document: how a finding's evidential weight was arrived at.

A verdict on its own is a conclusion a reader has to take on trust. This is the working
that produced it — the two competing propositions, the evidence trail, the two measured
quantities, the ratio, and the sensitivity envelope — with each branch pointing at the
ledger nodes it rests on.

**The shape is an argument, so the shape had to be chosen carefully.** A left-to-right flow
that culminates in a likelihood ratio presents the ratio as the natural endpoint of the
evidence, and that is the reading the library's own limitations text spends three
paragraphs resisting: a ratio is *not* robust to how the claim was selected, and a claim
harvested from a post was selected. Three structural choices push back:

* **The sensitivity envelope sits between the ratio and the band**, so a reader meets the
  fragility before the conclusion rather than beside it.
* **The band shown is the headline band** — the lower bound when the result is fragile —
  computed here rather than re-derived by a renderer that could drift from
  `chainlens.verify.likelihood.SensitivityReport.headline_band`.
* **A posterior never hangs off the evidence alone.** It is present only when a caller
  supplied a prior, and it names who did.

And the case that is *normal today* is a tree with a hole in it rather than one that stops
early: with no ratio there are no competing propositions to draw, so those are absent — drawing
a first/alternative pair above a number that does not exist would look broken — but the
calculation itself is drawn, with its formula and the input that stopped it. A reader sees
where the hole is rather than being told there is one, which is the difference between a
withheld number and an absent argument.

## `DerivationDocument`

One finding's derivation, as a document a front end can render.

**Attributes**

- `schema_version` `int` — the contract version. Both ends refuse an unknown major.
- `claim_id` `str` — derived from the claim, so a graph overlay can group findings by claim.
- `claim_quote` `str` — the verbatim span the claim was read from, so a reader can see what is being adjudicated without the graph.
- `verdict` `ClaimVerdict` — the categorical finding, repeated at the root because it is the thing the tree explains.
- `method` `str` — which checker produced the verdict.
- `has_ratio` `bool` — whether a likelihood ratio was reported. The tree's shape differs, and a renderer should not have to walk it to find out.
- `root` `DerivationNode` — the tree.
- `limitations` `str` — the standing caveats. **Replaced when a prior was supplied**, because the standard text says the library reports no posterior and a rendered posterior beside it would make the artifact contradict itself.
- `prior_supplied_by` `str | None` — who supplied the prior, when one was.
- `selection` `SelectionDisclosure | None` — how the claim came to be one of the claims priced, when a chooser picked it. On the document because the document is what a reader sees, and a ratio whose claim was chosen would otherwise render exactly like one whose claim was fixed in advance.

**Members**

- `schema_version` = 1
- `claim_id`
- `claim_quote`
- `verdict`
- `method`
- `has_ratio` = False
- `root`
- `limitations`
- `prior_supplied_by` = None
- `selection` = None

### `node_count`

How many steps the tree holds.

### `all_refs`

Every graph reference the derivation makes.

### `is_informative`

Whether the finding decided anything, as opposed to being unanswerable.

## `DerivationKind`

What one node of the derivation is.

The kinds are the *vocabulary of the argument*, not of the data: ``QUANTITY_K`` and
``QUANTITY_P`` are separate from ``EVIDENCE`` because a measured number and the finding
that produced it are different claims, and ``BECAUSE`` exists so the refusal case has a
node of its own rather than being smuggled into a verdict's label.

**Members**

- `CLAIM` = 'claim'
- `VERDICT` = 'verdict'
- `PROPOSITION` = 'proposition'
- `EVIDENCE` = 'evidence'
- `QUANTITY_K` = 'quantity_k'
- `QUANTITY_P` = 'quantity_p'
- `LIKELIHOOD_RATIO` = 'likelihood_ratio'
- `SENSITIVITY` = 'sensitivity'
- `VERBAL_BAND` = 'verbal_band'
- `POSTERIOR` = 'posterior'
- `ASSUMPTION` = 'assumption'
- `CAVEAT` = 'caveat'
- `BECAUSE` = 'because'

## `DerivationNode`

One step of a derivation, and everything a reader needs to disagree with it.

**Attributes**

- `id` `str` — a path-derived identifier, stable across runs — ``claim``, ``claim/evidence/0`` — so a renderer can key nodes and a fixture can be compared.
- `kind` `DerivationKind` — what this step is.
- `label` `str` — the short thing to show on the node. Written here rather than in the renderer, because a label the renderer invents is a claim the library did not make.
- `summary` `str | None` — a sentence, when the label is not enough.
- `detail` `tuple[DetailEntry, ...]` — labelled facts, in the tagged form a second language can render.
- `value` `float | None` — the number this step is about, when it is about one.
- `unit` `str | None` — what that number is counted in.
- `band` `VerbalScale | None` — the verbal band, on the band and posterior nodes.
- `graph_refs` `tuple[GraphRef, ...]` — the ledger nodes and edges this step rests on. Carried whether or not they resolve — see `chainlens.models.wire.GraphRef`.
- `input` `Input | None` — what this node *is*, when it is one of the values a calculation rests on. A quantity node carries one; every other node carries neither this nor ``operation``.
- `operation` `Operation | None` — the arithmetic, when this node is a number that was computed. Present whether or not it produced a result — an operation whose inputs are one-sided or unbound travels with its formula and no value, which is what makes a withheld number read as a hole in a visible calculation rather than as a refusal.
- `children` `tuple[DerivationNode, ...]` — the steps below this one.

**Members**

- `id`
- `kind`
- `label`
- `summary` = None
- `detail` = ()
- `value` = None
- `unit` = None
- `band` = None
- `graph_refs` = ()
- `input` = None
- `operation` = None
- `children` = ()

### `walk`

```python
walk() -> tuple[DerivationNode, ...]
```

This node and every node beneath it, depth first.

For a caller that wants to find every reference a derivation makes, or to assert
something about every node without recursing itself.

### `all_refs`

Every graph reference in the subtree, deduplicated and in order.
