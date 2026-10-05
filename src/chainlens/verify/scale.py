"""The ENFSI verbal scale for likelihood ratios, with configurable boundaries.

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
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Self

from pydantic import Field, model_validator

from chainlens.models.base import LensModel
from chainlens.models.enums import Proposition, VerbalScale

__all__ = ["DEFAULT_THRESHOLDS", "VerbalBand", "VerbalThresholds", "band_for"]


class VerbalThresholds(LensModel):
    """Upper bound of each verbal band, as a likelihood ratio.

    Strictly increasing, and each above 1, since an LR of 1 is "no support" and a
    band that reached down to it would have no lower edge.

    Attributes:
        slight: largest LR still called slight support. ENFSI default 10.
        moderate: ENFSI default 100.
        moderately_strong: ENFSI default 1000.
        strong: ENFSI default 10000; anything above is very strong.
    """

    slight: float = Field(default=10.0, gt=1.0)
    moderate: float = Field(default=100.0, gt=1.0)
    moderately_strong: float = Field(default=1_000.0, gt=1.0)
    strong: float = Field(default=10_000.0, gt=1.0)

    @model_validator(mode="after")
    def _strictly_increasing(self) -> Self:
        bounds = [self.slight, self.moderate, self.moderately_strong, self.strong]
        if any(lower >= upper for lower, upper in pairwise(bounds)):
            raise ValueError(f"verbal thresholds must be strictly increasing, got {bounds}")
        return self

    def band(self, ratio: float) -> VerbalScale:
        """The band for a ratio of 1 or more."""
        if ratio <= self.slight:
            return VerbalScale.SLIGHT
        if ratio <= self.moderate:
            return VerbalScale.MODERATE
        if ratio <= self.moderately_strong:
            return VerbalScale.MODERATELY_STRONG
        if ratio <= self.strong:
            return VerbalScale.STRONG
        return VerbalScale.VERY_STRONG


#: The ENFSI appendix boundaries. Override per institution if yours differ.
DEFAULT_THRESHOLDS = VerbalThresholds()


class VerbalBand(LensModel):
    """A likelihood ratio placed on the verbal scale.

    Attributes:
        ratio: the ratio the band was read from, always ``>= 1`` -- the LR itself
            when it supports the first proposition, its reciprocal when it
            supports the alternative.
        scale: the verbal band.
        supports: which proposition the evidence supports, ``NEITHER`` at LR 1.
        lr: the likelihood ratio as computed, before any reciprocal.
    """

    ratio: float = Field(ge=1.0)
    scale: VerbalScale
    supports: Proposition
    lr: float = Field(ge=0.0)

    @property
    def is_informative(self) -> bool:
        """Whether the evidence distinguishes the propositions at all."""
        return self.scale is not VerbalScale.NONE

    def __str__(self) -> str:
        if self.scale is VerbalScale.NONE:
            return "no support for either proposition (LR 1)"
        return (
            f"{self.scale.value} support for the {self.supports.value} proposition (LR {self.lr:g})"
        )


def band_for(lr: float, thresholds: VerbalThresholds = DEFAULT_THRESHOLDS) -> VerbalBand:
    """Place a likelihood ratio on the verbal scale.

    An infinite LR is allowed and lands in the top band. Callers should prefer to
    refuse a zero coincidence probability at its source rather than let an
    infinity reach a report, but the function must still have a defined answer.

    Raises:
        ValueError: if ``lr`` is negative or NaN. A negative likelihood ratio is
            not a small one, it is a mistake.
    """
    if math.isnan(lr) or lr < 0:
        raise ValueError(f"a likelihood ratio must be a non-negative number, got {lr!r}")
    if lr == 1:
        return VerbalBand(ratio=1.0, scale=VerbalScale.NONE, supports=Proposition.NEITHER, lr=1.0)
    if lr > 1:
        return VerbalBand(ratio=lr, scale=thresholds.band(lr), supports=Proposition.FIRST, lr=lr)

    # lr < 1: the alternative proposition is supported, and the band is read off
    # the reciprocal. Zero would divide by zero, so it is mapped to the top band.
    reciprocal = math.inf if lr == 0 else 1.0 / lr
    return VerbalBand(
        ratio=reciprocal,
        scale=thresholds.band(reciprocal),
        supports=Proposition.ALTERNATIVE,
        lr=lr,
    )
