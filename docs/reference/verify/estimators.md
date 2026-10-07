# `chainlens.verify.estimators`

The estimator that ships, and the one assumption it rests on.

A likelihood ratio needs a coincidence probability ``p`` — "how often does something that looks
like this happen anyway?" — and answering that needs a *sample* of transfers to count over. This
module draws that sample from what a provider can actually reach, and states plainly what the
sample is.

**The sample is the sender's own other movements, and that is a choice with a name.** The engine
reports it as ``NullModel.WITHIN_SENDER``: the alternative proposition being priced is "one of the
sender's *other* transfers coincidentally looks like the asserted payment". The competing
``POPULATION`` model — "a transfer of this shape is common network-wide" — needs a sample no
free provider can draw, and is refused here with its own reason rather than approximated from
something else. That refusal is the honest form of a real limitation: a network-wide rate would
be a different, and better, number, and this estimator cannot produce it.

Three further things are worth stating rather than discovering:

* **the sample is bounded.** Providers are read newest-first and a scan has a ceiling, so a busy
  address gives the *recent* history. When the ceiling bites, the estimate's ``population`` says
  so in words — "the sender's most recent N movements outside the window" — and the derivation
  renders that string verbatim, so a bounded sample cannot pass for an exhaustive one.
* **the window is the claim's, and it is the complement that is counted.** The claim's window is
  where the asserted transfer should be; the movements *inside* it are the opportunities ``k``,
  which the checker counts. A rate drawn from those would be circular, so the sample is what falls
  outside.
* **the sample is one asset's.** Base-unit amounts are only comparable within an asset, so the
  movements counted are the claim's asset and no other. On Bitcoin this is invisible — there is one
  asset — and on an account chain where an address moves ERC-20s it is the difference between a
  rate about this asset and a rate about a mixture.
* **nothing here decides anything.** The estimator returns a rate and the null it was drawn
  under. Whether a ratio is reported at all, and what it means, is the engine's and the
  likelihood module's business.

## `WindowCoincidenceEstimator`

```python
WindowCoincidenceEstimator(*, null_model: NullModel = NullModel.WITHIN_SENDER, sample_limit: int = DEFAULT_SAMPLE_LIMIT)
```

Prices a coincidence from the sender's own movements, as far back as a scan can reach.

**Parameters**

- `null_model` `NullModel`, default `NullModel.WITHIN_SENDER` — which coincidence mechanism to price. Only ``WITHIN_SENDER`` can be drawn from one address's history; anything else is refused with its reason.
- `sample_limit` `int`, default `DEFAULT_SAMPLE_LIMIT` — how many movements to read before stopping. A sample that hits this is described as bounded rather than presented as the whole history.

### `estimate`

```python
estimate(elements: ClaimElements, *, provider: Provider) -> RateEstimate | Unpriced | None
```

## `DEFAULT_SAMPLE_LIMIT`

## `estimator_for`

```python
estimator_for(provider: Provider, *, null_model: NullModel = NullModel.WITHIN_SENDER) -> CoincidenceEstimator | None
```

An estimator when the provider can supply what one needs, and ``None`` when it cannot.

``None`` rather than an estimator that always refuses: the engine's "no coincidence estimator
is configured" reason is the honest one when there is nothing to configure, and a refusal
dressed as a data problem would send a reader looking for data that would not help.
