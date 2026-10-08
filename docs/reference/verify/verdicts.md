# `chainlens.verify.verdicts`

What the chain showed, what it is worth, and the line between them.

The verdict rule, stated once so no checker has to re-derive it:

============================  ==================================================
`ClaimVerdict`           when
============================  ==================================================
``SUPPORTED``                 chain data is consistent with the claim
``CONTRADICTED``              chain data rules it out, including an identifier
                              that does not exist
``UNRESOLVED``                nothing decided it, and the finding's ``gap`` says
                              what is missing
============================  ==================================================

**Three members, and the third is not a finding about the claim.** It says nothing was
decided, and the finding carries a `chainlens.models.calculation.Input` with no value
naming what is missing. That input's *kind* holds the distinction that used to be two verdict
members, and the distinction is worth stating because it survives intact: ``no_method`` says
*stop asking* — "I own this address" is not a claim about the ledger, and attribution labels
come from a third party rather than from the chain, so with no label source configured there is
no method here rather than a missing datum — while ``no_data`` says *configure something*,
because a transfer claim against a provider that cannot list an address's transactions is
answerable in principle and blocked in practice. Collapsing those two into one "unknown" would
hide both the reason and the remedy.

What changed is where the distinction lives. It was two verdict members, which meant the same
idea was spelled twice — once as a verdict, which is a finding about a claim, and once as a
property of the input that is missing, which "we did not decide" actually is.

The other line this module holds: **the verdict and the likelihood ratio are
independent.** The verdict is computed from chain data; the ratio is attached to
it, never derived from it. A ratio of 500 does not make anything ``SUPPORTED``,
and nothing here can promote a ``CONTRADICTED`` claim — the ratio is mathematically
never below 1, so a contradicted claim can never carry one at all.

## `ClaimEvidence`

What the chain showed, and where every figure in it came from.

An amount a reader cannot trace back to a transaction is an assertion rather
than evidence, so the transfers themselves are carried rather than summarised
into a total.

**Attributes**

- `provider` `str | None` — which provider answered, when one did.
- `endpoint` `str | None` — the endpoint or method, for a reader who wants to re-run it.
- `txids` `tuple[str, ...]` — every transaction id the finding rests on.
- `transfers` `tuple[Transfer, ...]` — the movements found, capped at the engine's record limit.
- `transfers_truncated` `bool` — whether that cap was hit, so a partial list is never read as the whole of it.
- `candidates_considered` `int | None` — ``k``, how many of the sender's own transfers were examined for a coincidence. ``None`` when the claim does not have that shape.
- `scan_complete` `bool | None` — whether the scan that produced ``k`` was exhausted. ``None`` when no scan was involved. A ``False`` here is what forbids a ratio: an under-counted ``k`` inflates it.
- `apportioned_shares` `Mapping[str, int]` — the inferred shares that matter to this outcome, keyed by edge key, and only where they disagree with a value the ledger recorded. On a match, the share of each matched output; on a contradiction, the shares that would have satisfied the claim when no recorded value did — the near-miss, reported so a reader can see which of two figures the chain wrote down. Never used to decide the verdict.
- `detail` `Mapping[str, Any]` — checker-specific facts a reviewer would want and no general field fits — a balance observed, a label asserted, a cluster size.
- `provenance` `tuple[Provenance, ...]` — one record per fetch, so a run can be replayed or audited.
- `warnings` `tuple[str, ...]` — anything that qualified the check without changing the verdict.

**Members**

- `provider` = None
- `endpoint` = None
- `txids` = ()
- `transfers` = ()
- `transfers_truncated` = False
- `apportioned_shares` = Field(default_factory=dict)
- `candidates_considered` = Field(default=None, ge=0)
- `scan_complete` = None
- `detail` = Field(default_factory=dict)
- `provenance` = ()
- `warnings` = ()

### `is_empty`

Whether this evidence supports nothing at all.

## `CoincidenceEstimator`

Supplies the coincidence probability ``p`` for a claim's priced elements.

The engine ships **no default implementation**, and that is the design rather
than a gap. Estimating ``p`` needs transfers *in a window*, which a per-address
provider cannot supply; the alternative would be a constant, and a constant
would be an invented rate wearing a measurement's clothes. With no estimator
configured, a finding simply carries no ratio and says why.

An implementation returns ``None`` when the sample it can reach is too thin to
price the coincidence, which is a normal answer for a rare recipient — and an
`Unpriced` when it can say *why* it will not price one, which the engine puts
into the finding verbatim.

### `estimate`

```python
estimate(elements: ClaimElements, *, provider: Provider) -> RateEstimate | Unpriced | None
```

## `RateEstimate`

```python
RateEstimate(component: ComponentEstimate, null_model: NullModel)
```

A coincidence rate, and the null it was estimated under.

The two travel together because the null model is a property of *how the sample
was drawn*, not a label applied afterwards: a rate counted over the sender's own
other transfers and a rate counted over the network at large answer different
questions, and a bare float cannot say which one it is. Reporting the wrong null
errs in a direction that depends on the claim — see the engine's docstring.

**Attributes**

- `component` `ComponentEstimate` — the estimated probability, with its sample size and interval.
- `null_model` `NullModel` — which coincidence mechanism the sample describes.

**Members**

- `component`
- `null_model`

## `Unpriced`

```python
Unpriced(reason: str, samples: int | None = None, kind: UnboundKind = UnboundKind.NO_DATA)
```

A refusal to price, in the estimator's own words.

``None`` already means one thing: the sample the estimator could reach was too thin to price.
This is for the refusals an estimator can *diagnose* — the claim names no window, the sender
has nothing outside it to compare against, the null model needs a sample no provider can draw
— where collapsing them into one generic sentence would hide the reason, and the reason is the
part a caller can act on.

**Attributes**

- `reason` `str` — what stopped it, phrased for the derivation's ``because`` node, which renders it verbatim.
- `samples` `int | None` — how many movements the estimator got to look at, when it looked at any.
- `kind` `UnboundKind` — which of the three answers this refusal is. The estimator is the only thing that knows, and the difference is what a reader acts on: a claim with no window wants a window, a provider that cannot list movements wants a different provider, and the population null model wants a reader to stop asking, because no free provider enumerates a network-wide sample. Guessing ``no_data`` for all three would put a limit of the data on the same footing as a limit of the method.

**Members**

- `reason`
- `samples` = None
- `kind` = UnboundKind.NO_DATA

## `VerificationFinding`

One claim, adjudicated, with everything a reader needs to disagree.

**Attributes**

- `post_id` `str` — the post the claim was read from.
- `provenance_strength` `ProvenanceStrength` — how that post's content was obtained. Carried here as well as on the report because the two are genuinely independent: a chain claim in a hand-supplied screenshot can be ``SUPPORTED``, because the chain data is real whatever the post is, and stating the strength beside the verdict is the difference between an honest tool and one that launders a screenshot into a finding.
- `claim` `Claim` — the claim as extracted, unchanged.
- `verdict` `ClaimVerdict` — the categorical finding.
- `method` `str` — which checker produced it, so a reader can go and read that method.
- `reason` `str | None` — the machine-readable explanation, always present when no ratio is reported and always present for the two unanswerable verdicts. **Being retired**: it is derived from `attempt` while the derivation builder is migrated, and disappears when nothing reads it.
- `elements` `ClaimElements | None` — what was priced, when the claim reduced to something priceable.
- `evidence` `ClaimEvidence` — what the chain showed.
- `likelihood` `LikelihoodRatio | None` — the weight of the evidence, when it could be priced at all.
- `attempt` `RatioAttempt | None` — what a ratio would have rested on, whether or not one was reported. The inputs with their bindings, and the operation with its formula — so a withheld ratio travels as a calculation with a hole in it rather than as a sentence.
- `gap` `Input | None` — the one unbound input this finding turns on, when it turns on one. A checker that could not answer says so here, and so does a ratio that was withheld because an input was missing — the two are the same shape, which is the point.
- `assumptions` `tuple[str, ...]` — what the result rests on, including every convention applied.
- `caveats` `tuple[str, ...]` — what would change it.
- `selection` `SelectionDisclosure | None` — how this claim came to be one of the claims priced, when a chooser picked it. Carried on the finding rather than only on the record it was written from, because a consumer of a finding has to be able to see that a ratio prices a *chosen* claim — and a reader who sees only the finding would otherwise read the number as pre-registered.

**Members**

- `post_id`
- `provenance_strength`
- `claim`
- `verdict`
- `method`
- `reason` = None
- `gap` = None
- `elements` = None
- `evidence` = Field(default_factory=lambda: ClaimEvidence())
- `likelihood` = None
- `attempt` = None
- `selection` = None
- `assumptions` = ()
- `caveats` = ()

### `is_informative`

Whether the evidence distinguishes anything at all.

False for the verdict that means "no answer", which a caller rendering a table needs to
tell apart from a finding that went one way or the other. The predicate itself lives on
the verdict, because a derivation asks the same question of the same enum.

### `has_ratio`

Whether a likelihood ratio was reported.

## `VerificationReport`

Every claim in one post, and the frame they should be read in.

**Attributes**

- `post_id` `str` — the post the findings were read from.
- `provenance_strength` `ProvenanceStrength` — how the post's content was obtained.
- `findings` `tuple[VerificationFinding, ...]` — one per claim, including the ones that could not be checked.
- `warnings` `tuple[str, ...]` — post-level problems — dropped claims, unreadable media, an extraction that produced nothing.
- `limitations` `str` — the standing caveats, carried on the artifact rather than in a README, because a number without its caveats travels badly.

**Members**

- `post_id`
- `provenance_strength`
- `findings` = ()
- `warnings` = ()
- `limitations` = STANDARD_VERIFICATION_LIMITATIONS

### `counts`

How many findings landed on each verdict, including the zeroes.

Every member is present, so a caller can render a fixed set of rows and a
missing verdict reads as zero rather than as a missing key.

### `is_informative`

Whether any finding actually decided anything.

### `with_ratio`

The findings that carry a likelihood ratio.

## `STANDARD_VERIFICATION_LIMITATIONS`
