# `chainlens.verify.engine`

Adjudicating a post's claims against chain data, deterministically.

This module is where the central invariant is enforced rather than asserted: it
takes an `chainlens.verify.schema.Extraction` — the only thing a model
produces — and returns a `chainlens.verify.verdicts.VerificationReport`
whose every verdict was computed here, from provider responses. **No model output
reaches a verdict.** The extraction contributes a claim, a quote and some text; it
does not contribute a finding, a number or a direction of travel.

The other job is the likelihood ratio, and the separation matters as much. A
checker reports what the chain showed and how completely it looked; the engine
decides whether that is enough to justify a ratio, and the arithmetic lives in
`chainlens.verify.likelihood`. A ratio is attached to a verdict, never derived
from one.

**Where there is no ratio, there is still the calculation.** Every finding carries a
`chainlens.models.calculation.RatioAttempt` — the inputs with their bindings and
the operation with its formula — whether or not a number came out. A withheld ratio is
therefore a formula with a hole at a named place rather than a sentence in place of an
argument, and the hole says which of three things it is:

* ``k`` is bound but one-sided, because the scan was not exhaustive, so the ratio would be
  inflated by an unknown amount;
* ``k`` is 0, a value that is known and on which the arithmetic has no answer, because a
  sender with no movements in the window offered no opportunity for a coincidence;
* ``p`` is unbound — no method here can obtain it, or the data was not reachable, or the
  caller said not to price this run at all.

That last trio is the distinction this module used to lose: all three arrive as "there is
no estimator", and they want three different things from a reader.

## `VerificationEngine`

```python
VerificationEngine(provider: Provider, *, estimator: CoincidenceEstimator | None = None, registry: CheckerRegistry | None = None, scan_limit: int | None = None, transfer_limit: int | None = None, card: Keycard = SHIPPED, thresholds: VerbalThresholds = DEFAULT_THRESHOLDS, estimate_requested: bool = True, selection: SelectionDisclosure | None = None)
```

Adjudicates claims from one post against one provider.

**Parameters**

- `provider` `Provider` — the chain data source.
- `estimator` `CoincidenceEstimator | None`, default `None` — supplies the coincidence probability, when one is configured. The default is ``None``: no ratio is then reported and every finding says why. See `chainlens.verify.verdicts.CoincidenceEstimator`.
- `registry` `CheckerRegistry | None`, default `None` — the claim-type to checker mapping. Defaults to the shipped checkers; pass a copy to add one for a single run.
- `scan_limit` `int | None`, default `None` — how many transactions to walk before declaring a scan truncated.
- `transfer_limit` `int | None`, default `None` — how many transfers to carry into a finding's evidence.
- `thresholds` `VerbalThresholds`, default `DEFAULT_THRESHOLDS` — the verbal-scale boundaries. ENFSI-aligned by default, and configurable because the guideline treats the scale as jurisdiction-dependent.
- `card` `Keycard`, default `SHIPPED` — the data this run is entitled to rest an answer on. The two limits above default to the card's entries; a card is a *value a caller holds* and never a global this reads, so two engines in one process can be run under two different cards.
- `estimate_requested` `bool`, default `True` — whether anybody wanted a coincidence priced. Says nothing about whether one *could* be: with no estimator, this field is the difference between a caller who decided against it and a setup that never had one, and the two read differently on an artifact because they are fixed differently.

### `provider`

The provider claims are checked against.

### `verify_post`

```python
verify_post(post: Post, extraction: Extraction) -> VerificationReport
```

Adjudicate every claim in ``extraction``, in the order they appear.

Claims are also validated against the post first: a claim whose quote is not
in the post is dropped rather than answered, and the drop is reported. A
dropped claim is a statement about the extraction, and letting one through
would mean publishing a verdict about something the post never said.

### `verify_claim`

```python
verify_claim(claim: Claim, post: Post) -> VerificationFinding
```

Adjudicate one claim, and attach a ratio only where one is justified.
