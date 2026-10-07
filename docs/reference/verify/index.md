# `chainlens.verify`

Claim verification: categorical findings, and the weight of the evidence.

The layer separates two things that are easy to conflate and dangerous to merge:

* a `chainlens.models.enums.ClaimVerdict` — what the chain *shows*;
* a `chainlens.verify.likelihood.LikelihoodRatio` — how much that is
  *worth*.

Neither is derived from the other. A verdict is computed from chain data; the ratio
is attached to it. The library deliberately produces no posterior probability,
because choosing the prior is not its call — see
`chainlens.verify.likelihood.LikelihoodRatio.posterior_probability`, which
requires the caller to supply one.
