# `chainlens.verify.scale`

The ENFSI verbal scale for likelihood ratios, with configurable boundaries.

The scale is the one in the appendix of the *ENFSI Guideline for Evaluative
Reporting in Forensic Science* (2015):

===============  ==================
LR               support for the first proposition
===============  ==================
= 1              none for either
1 < LR <= 10     slight / limited
10 < LR <= 100   moderate
100 < LR <= 1000 moderately strong
1000 < LR <= 10⁴ strong
> 10⁴            very strong
===============  ==================

Two things about it are load-bearing and easy to miss:

* **It is symmetric.** An LR below 1 supports the *alternative* proposition, with
  the band read off ``1/LR``. The direction is therefore carried separately from
  the magnitude, because the magnitude alone cannot tell you which side it favours.
* **The boundaries are not universal.** The guideline treats the verbal scale as
  optional and jurisdiction-dependent, prefers the numeric ratio where one can be
  given, and its own main table uses a finer top end than its appendix. So the
  thresholds are a frozen, caller-overridable model rather than constants, and the
  default is described as ENFSI-aligned rather than as the standard.

## `VerbalBand`

A likelihood ratio placed on the verbal scale.

**Attributes**

- `ratio` `float` — the ratio the band was read from, always ``>= 1`` -- the LR itself when it supports the first proposition, its reciprocal when it supports the alternative.
- `scale` `VerbalScale` — the verbal band.
- `supports` `Proposition` — which proposition the evidence supports, ``NEITHER`` at LR 1.
- `lr` `float` — the likelihood ratio as computed, before any reciprocal.

**Members**

- `ratio` = Field(ge=1.0)
- `scale`
- `supports`
- `lr` = Field(ge=0.0)

### `is_informative`

Whether the evidence distinguishes the propositions at all.

## `DEFAULT_THRESHOLDS`

## `band_for`

```python
band_for(lr: float, thresholds: VerbalThresholds = DEFAULT_THRESHOLDS) -> VerbalBand
```

Place a likelihood ratio on the verbal scale.

An infinite LR is allowed and lands in the top band. Callers should prefer to
refuse a zero coincidence probability at its source rather than let an
infinity reach a report, but the function must still have a defined answer.

**Raises**

- `ValueError` — if ``lr`` is negative or NaN. A negative likelihood ratio is not a small one, it is a mistake.
