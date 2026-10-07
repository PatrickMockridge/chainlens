# `chainlens.models.calculation`

What a number rests on, and what happened to it.

This module exists because the library used to say a great deal about *not* answering. A ratio came
with a reason string; a verdict carried two members for not answering, which its own
docstring admits look identical in a report; an estimator could refuse with `Unpriced` or with
`None`, and the two collapsed into the same slot, so a reader could not tell a diagnosed refusal
from a thin sample.
Sixteen such vocabularies grew up, and the only thing they shared was that each was a sentence.

What replaces them is two questions, asked of every value a conclusion rests on:

* **is it bound?** and if not, *why not* — and there are exactly three answers, because a value
  can be missing for exactly three reasons: nothing here could obtain it (``no_method``),
  something could and the data was not reachable (``no_data``), or nobody asked
  (``not_requested``). The third was discovered rather than invented: at ``ui/cli.py`` the
  estimator is ``estimator_for(provider) if estimate else None``, so ``--no-estimate``, a provider
  that cannot draw the sample, and an engine built with no estimator all arrive as the same
  ``None``, described by one sentence that is only true for one of them.
* **how good is the bound?** because a lower bound is not a value. A truncated scan makes the count
  of opportunities a lower bound, a sparse sample makes the coincidence rate an upper bound, and an
  infinite ratio is a result with a lower bound and no point. Those were three bespoke booleans
  (`scan_complete`, `is_upper_bound`, `lr_at_least`) and are now one word.

`Input` and `Operation` are the two carriers, and the rule between them is one line:
**an operation emits its result when, and only when, every input it names is bound exactly.** Where
that fails, the operation still travels — with its formula and its inputs — so an artifact
carries a calculation with a hole in it rather than a sentence in place of a calculation.

## `Binding`

Whether an input has a value at all.

**Members**

- `BOUND` = 'bound'
- `UNBOUND` = 'unbound'

## `BoundDirection`

How much of a value a bound gives.

``POINT`` is the value itself. ``LOWER`` and ``UPPER`` are one-sided: the true number is at or
above (or at or below) this one, and which way the error runs is stated rather than implied.

This is deliberately *not* fused into `Binding`. "Is there a value" and "how good is it"
are different questions, and a truncated scan answers the first with yes and the second with
``LOWER`` — which a single enum could only express by inventing a member per combination.

**Members**

- `POINT` = 'point'
- `LOWER` = 'lower'
- `UPPER` = 'upper'

## `Input`

One value a calculation rests on, and everything about where it stands.

The two halves are disjoint and a validator enforces it: bound inputs carry a value and a
source, unbound ones carry a kind and a reason. That is the structural guarantee replacing the
prose vocabularies — there is no construction in which an input both has a value and does not.

**Attributes**

- `name` `str` — the stable slot this input fills — ``k``, ``p``, ``band``, ``prior``. What `Operation.inputs` refers to.
- `label` `str` — what to show a reader. Written here rather than in a renderer, for the reason `chainlens.models.derive.DerivationNode` gives: a label a renderer invents is a claim the library did not make.
- `value` `float | None` — the number, when bound. A count is stored here as well as in ``detail`` — see the note below.
- `unit` `str | None` — what the value is counted in.
- `direction` `BoundDirection` — whether the value is the number or a one-sided bound on it.
- `source` `Source | None` — where a bound value came from.
- `kind` `UnboundKind | None` — why an unbound one has none.
- `reason` `str | None` — the sentence explaining an unbound one, in the words of whoever refused.
- `detail` `tuple[DetailEntry, ...]` — anything else a reader needs, in the tagged form a second language can render.

A note on precision: ``value`` is a float, matching `DerivationNode`, and exact integers
travel in ``detail`` as `chainlens.models.wire.DetailEntry` — which serialises an int
as a string for the reason its own docstring gives. Base-unit amounts need that; the counts here
(bounded by the scan limit) do not, so they are not given a third convention of their own.

**Members**

- `name`
- `label`
- `binding`
- `value` = None
- `unit` = None
- `direction` = BoundDirection.POINT
- `source` = None
- `kind` = None
- `reason` = None
- `detail` = ()

### `is_exact`

Whether this input is the number itself rather than a bound on it.

The single condition an operation checks. A lower bound is not a value, so a calculation
resting on one is withheld rather than run — which is what stops a truncated scan
producing an inflated ratio under a flag nobody reads.

## `Operation`

One arithmetic step, with the formula it is.

The formula is not written here. It comes from
`chainlens.verify.likelihood.formula_for`, which sits beside the functions that compute
the numbers, so the displayed formula and the computed value have one home rather than two. A
test evaluates the formula string against the function over a grid, which is what catches an
edit to one that missed the other.

**Attributes**

- `kind` `OperationKind` — which operation this is.
- `formula` `str` — the canonical expression, for a reader and for that test.
- `inputs` `tuple[str, ...]` — the **names** of the inputs it consumes, in argument order. Names rather than node ids, because an `RatioAttempt` carries these on a finding, where there is no tree to point into.
- `result` `float | None` — the number, when every input is bound exactly and the answer is defined.
- `direction` `BoundDirection` — whether `result` is the answer or a one-sided bound on it. An infinite ratio is the case that needs this: the top of the scale is a floor, not the value.
- `reason` `str | None` — why there is no number, when there is none.

**Members**

- `kind`
- `formula`
- `inputs`
- `result` = None
- `direction` = BoundDirection.POINT
- `reason` = None

## `OperationKind`

Which arithmetic was done. One member per formula the library has.

**Members**

- `COINCIDENCE` = 'coincidence'
- `LIKELIHOOD_RATIO` = 'likelihood_ratio'
- `POSTERIOR` = 'posterior'

## `RatioAttempt`

Everything one attempt to price a coincidence rests on.

Carried on a finding beside the ratio rather than instead of it, because the ratio is what a
report quotes and this is what a reader checks it against. A finding whose attempt has an
unbound or one-sided input has no ratio, and the hole is visible here rather than being a
sentence somewhere else on the artifact.

**Members**

- `inputs` = ()
- `operation` = None

### `by_name`

```python
by_name(name: str) -> Input | None
```

The input filling ``name``, or ``None``. Used by renderers and by the drift test.

## `Source`

Where a bound value came from.

``text`` is the sentence a reader needs — "the sender's movements in the window", "the hedge
word '~' licenses a 5% band" — and ``kind`` is the part a machine can act on, so that a
convention can be told from a measurement without reading prose.

**Members**

- `kind`
- `text`

## `SourceKind`

What kind of thing put a value where it is.

A reader deciding how much to trust a number needs to know whether it was read off the chain,
tallied from reads, priced from a sample, chosen by convention, or handed in by somebody — and
"chosen by convention" is the kind most easily mistaken for a measurement, which is why it is a
kind rather than a footnote.

**Members**

- `OBSERVED` = 'observed'
- `COUNTED` = 'counted'
- `ESTIMATED` = 'estimated'
- `CONVENTION` = 'convention'
- `SUPPLIED` = 'supplied'
- `ASSUMED` = 'assumed'

## `UnboundKind`

Why an input has no value.

These are the three answers, and they are not interchangeable: the first says stop
asking, the second says configure something or wait for data, and the third says nobody
asked. A reader who cannot tell them apart cannot tell a gap in their own setup from a
limit of the chain.

**Members**

- `NO_METHOD` = 'no_method'
- `NO_DATA` = 'no_data'
- `NOT_REQUESTED` = 'not_requested'
