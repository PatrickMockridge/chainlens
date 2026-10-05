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

from chainlens.verify.checks import (
    DEFAULT_SCAN_LIMIT,
    DEFAULT_TRANSFER_LIMIT,
    CheckContext,
    Checker,
    CheckerRegistry,
    CheckOutcome,
    default_registry,
)
from chainlens.verify.claims import ActivityWindow, AmountBand, ClaimElements
from chainlens.verify.engine import VerificationEngine
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
from chainlens.verify.parsing import (
    HEDGE_TOLERANCE,
    AmountReading,
    ParsedClaim,
    normalise_address,
    parse_amount,
    parse_claim,
)
from chainlens.verify.scale import (
    DEFAULT_THRESHOLDS,
    VerbalBand,
    VerbalThresholds,
    band_for,
)
from chainlens.verify.schema import Claim, ClaimType, Extraction, QuoteValidation, validate_quotes
from chainlens.verify.verdicts import (
    STANDARD_VERIFICATION_LIMITATIONS,
    ClaimEvidence,
    CoincidenceEstimator,
    RateEstimate,
    VerificationFinding,
    VerificationReport,
)

__all__ = [
    "DEFAULT_SCAN_LIMIT",
    "DEFAULT_THRESHOLDS",
    "DEFAULT_TRANSFER_LIMIT",
    "HEDGE_TOLERANCE",
    "MIN_JOINT_SUCCESSES",
    "STANDARD_VERIFICATION_LIMITATIONS",
    "ActivityWindow",
    "AmountBand",
    "AmountReading",
    "CheckContext",
    "CheckOutcome",
    "Checker",
    "CheckerRegistry",
    "Claim",
    "ClaimElements",
    "ClaimEvidence",
    "ClaimType",
    "CoincidenceEstimator",
    "ComponentEstimate",
    "EstimatorMethod",
    "Extraction",
    "LikelihoodRatio",
    "NullModel",
    "ParsedClaim",
    "QuoteValidation",
    "RateEstimate",
    "SensitivityReport",
    "Sweep",
    "VerbalBand",
    "VerbalThresholds",
    "VerificationEngine",
    "VerificationFinding",
    "VerificationReport",
    "band_for",
    "coincidence_probability",
    "default_registry",
    "evaluate_likelihood",
    "likelihood_ratio",
    "linearisation_relative_error",
    "normalise_address",
    "parse_amount",
    "parse_claim",
    "sensitivity_report",
    "validate_quotes",
    "wilson_interval",
]
