# `chainlens.ledger.derive`

Building a derivation from a finding, without adding anything to it.

Every node in the tree reads a field that already exists on
`chainlens.verify.verdicts.VerificationFinding` or on the
`chainlens.verify.likelihood.LikelihoodRatio` attached to it. Nothing is inferred,
nothing is recomputed, and no label is composed from a number — which matters, because a
derivation view is exactly where a renderer would be tempted to say "strong evidence" in
its own words. It says what the library said.

Two shapes, decided by whether a ratio was reported:

**With a ratio** the tree is the argument: the claim, the two competing propositions, the
evidence, the measured quantities ``k`` and ``p``, the ratio, and then — deliberately
*before* the verbal band — the sensitivity envelope that qualifies it.

**Without a ratio** — the normal case today, because no coincidence estimator ships — the
tree carries no competing propositions, because there is no number for them to compete over.
It carries the calculation instead: the inputs the finding did obtain, and the formula with
the input it did not. A reader sees where the hole is rather than being told there is one,
which is the difference between a withheld number and an absent argument.

A finding with no attempt at all — a contradicted claim, whose ratio is unavailable in
principle rather than withheld — keeps the shorter shape, with the reason on a ``because``
node. The reason string is reproduced verbatim there too: it is the verdict's own wording.

## `PRIOR_LIMITATIONS`

## `claim_id`

```python
claim_id(quote: str, *, chain_suffix: str = '') -> str
```

A stable identifier for a claim, from its own text.

Content-addressed rather than positional, so a claim keeps its identity when the
findings around it are reordered — which matters because the graph overlay groups
evidence by claim and a reordering must not silently re-attribute it.

## `derive_finding`

```python
derive_finding(finding: VerificationFinding, *, prior: float | None = None, prior_supplied_by: str = 'the caller') -> DerivationDocument
```

Build the derivation for one finding.

**Parameters**

- `finding` `VerificationFinding` — what the engine produced. Nothing is added to it.
- `prior` `float | None`, default `None` — a base rate, if the caller has one. **Absent by default** — the library ships no prior, and a posterior without one would rest on a base rate this code invented. Supplying one is the decision-maker's choice, which is why the parameter exists and why nothing defaults it.
- `prior_supplied_by` `str`, default `'the caller'` — who chose it, recorded on the posterior node.

**Raises**

- `ValueError` — the finding was not resolved and carries nothing saying why. A reader must not be able to read that verdict as an accusation, so the derivation refuses to render it without the engine's own explanation of what is missing.

## `finding_refs`

```python
finding_refs(finding: VerificationFinding) -> tuple[GraphRef, ...]
```

Every key a finding touches: its transactions, its endpoints, and its movements.

Public because two places need it and they must agree. The derivation tree puts each
reference on the step it belongs to, so a reader can see *which* fact rests on *which*
output; the evidence overlay puts them all on one item, because a finding is one
assertion. Sharing this function is what keeps the two from spelling a key differently —
and a disagreement would not look like a bug, it would look like a graph with no
evidence attached.

An edge reference is included where it can be named, which is the concrete thing the
bipartite view buys: ``ValueFlow`` keeps only its first contributor's index, so a flow
edge cannot point at one output, while ``{txid}:out:{index}`` can.
