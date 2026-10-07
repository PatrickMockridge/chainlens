# `chainlens.verify.claims`

A claim reduced to the elements that can actually be priced.

Before any probability can be computed, a sentence has to become a set of
checkable elements: which chain, which asset, which sender, and optionally a
recipient, an amount with a tolerance, and a window.

The amount tolerance is not a detail. It is the single largest free parameter in
the whole calculation — it comes from an extraction's reading of a word like
"approximately" — and it moves the likelihood ratio roughly linearly. It is a
first-class field here, and the sensitivity analysis sweeps it, precisely so that
its influence is visible rather than hidden inside a parser.

## `ActivityWindow`

The time range the claim refers to, with its edges stated explicitly.

Edge semantics are carried because they change ``k``, the count of the sender's
transfers: a block at exactly the boundary is either inside or outside, and an
off-by-one there silently changes the coincidence probability.

**Attributes**

- `start` `AwareDatetime` — earliest moment included.
- `end` `AwareDatetime` — latest moment included.
- `start_inclusive` `bool` — whether a transaction exactly at ``start`` counts.
- `end_inclusive` `bool` — whether a transaction exactly at ``end`` counts.

**Members**

- `start`
- `end`
- `start_inclusive` = True
- `end_inclusive` = True

### `contains`

```python
contains(moment: AwareDatetime | None) -> bool
```

Whether ``moment`` falls inside the window.

A transaction with no timestamp is **not** inside: unknown is not the same
as included, and silently counting it would inflate ``k``.

## `AmountBand`

An amount and how far from it the claim would still be counting.

In integer base units, like every other amount in the library — a float here
would be a way for 0.1 BTC to become 0.09999999999.

**Attributes**

- `nominal` `int` — the asserted amount, in base units.
- `tolerance` `int` — how far either side still counts as the same amount. Zero means exact. This is the claim's own precision, not the provider's.
- `asset` `AssetRef` — what is being counted.
- `at_least` `bool` — the claim asserted a lower bound ("more than 40,000") rather than an amount. Then ``nominal`` is the bound and only ``nominal - tolerance`` upward counts.

**Members**

- `nominal` = Field(ge=0)
- `tolerance` = Field(default=0, ge=0)
- `asset`
- `at_least` = False

### `contains`

```python
contains(amount: int) -> bool
```

Whether ``amount`` falls inside the band.

### `relative_tolerance`

Tolerance as a fraction of the nominal amount.

``math.inf`` for a zero nominal amount, because any tolerance around zero
is proportionally unbounded. Reported rather than clamped: a claim of
"about 0 BTC" is degenerate and should look degenerate.

### `scaled`

```python
scaled(factor: float) -> AmountBand
```

The same band with its tolerance multiplied, for the sensitivity sweep.

## `ClaimElements`

The parts of a claim that an analysis can be run against.

**Attributes**

- `chain` `Chain` — which chain the claim is about.
- `asset` `AssetRef` — the asset being moved.
- `sender` `str` — the address the claim attributes the transfer to.
- `recipient` `str | None` — the address claimed to receive, when the claim names one.
- `band` `AmountBand | None` — the claimed amount and tolerance, when the claim names one.
- `window` `ActivityWindow | None` — the claimed period, when the claim names one.

**Members**

- `chain`
- `asset`
- `sender`
- `recipient` = None
- `band` = None
- `window` = None

### `priced_elements`

Which elements the coincidence probability will be computed over.

Reported alongside the result so a reader can see what the number was
actually conditioned on — "recipient and amount" and "amount alone" are
very different claims that produce the same shape of output.
