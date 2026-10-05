"""Claim verification: categorical findings, and the weight of the evidence.

The layer separates two things that are easy to conflate and dangerous to merge:

* a :class:`~chainlens.models.enums.ClaimVerdict` — what the chain *shows*;
* a :class:`~chainlens.verify.likelihood.LikelihoodRatio` — how much that is
  *worth*.

Neither is derived from the other. A verdict is computed from chain data; the ratio
is attached to it. The library deliberately produces no posterior probability,
because choosing the prior is not its call — see
:meth:`~chainlens.verify.likelihood.LikelihoodRatio.posterior_probability`, which
requires the caller to supply one.
"""

from __future__ import annotations

from chainlens.verify.claims import ActivityWindow, AmountBand, ClaimElements
from chainlens.verify.likelihood import (
    MIN_JOINT_SUCCESSES,
    ComponentEstimate,
    EstimatorMethod,
    LikelihoodRatio,
    NullModel,
    SensitivityReport,
    Sweep,
    coincidence_probability,
    evaluate_likelihood,
    likelihood_ratio,
    linearisation_relative_error,
    sensitivity_report,
    wilson_interval,
)
from chainlens.verify.scale import (
    DEFAULT_THRESHOLDS,
    VerbalBand,
    VerbalThresholds,
    band_for,
)

__all__ = [
    "DEFAULT_THRESHOLDS",
    "MIN_JOINT_SUCCESSES",
    "ActivityWindow",
    "AmountBand",
    "ClaimElements",
    "ComponentEstimate",
    "EstimatorMethod",
    "LikelihoodRatio",
    "NullModel",
    "SensitivityReport",
    "Sweep",
    "VerbalBand",
    "VerbalThresholds",
    "band_for",
    "coincidence_probability",
    "evaluate_likelihood",
    "likelihood_ratio",
    "linearisation_relative_error",
    "sensitivity_report",
    "wilson_interval",
]
