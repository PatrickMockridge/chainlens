"""Adjudicating a post's claims against chain data, deterministically.

This module is where the central invariant is enforced rather than asserted: it
takes an :class:`~chainlens.verify.schema.Extraction` — the only thing a model
produces — and returns a :class:`~chainlens.verify.verdicts.VerificationReport`
whose every verdict was computed here, from provider responses. **No model output
reaches a verdict.** The extraction contributes a claim, a quote and some text; it
does not contribute a finding, a number or a direction of travel.

The other job is the likelihood ratio, and the separation matters as much. A
checker reports what the chain showed and how completely it looked; the engine
decides whether that is enough to justify a ratio, and the arithmetic lives in
:mod:`chainlens.verify.likelihood`. A ratio is attached to a verdict, never derived
from one, and it is withheld — with a machine-readable reason in its place — in
every case where the model's preconditions do not hold:

* no matching transfer was found (absence is a categorical finding, never a number);
* the scan was not exhaustive, so ``k`` is a lower bound and would inflate the ratio;
* the sender made no transfers at all, so there was no opportunity to price;
* no coincidence estimator is configured, which is the default, because estimating
  ``p`` needs a window of transfers that a per-address provider cannot supply.

That last one is the whole reason this module ships no estimator: the alternative
is a constant, and a constant here would be an invented rate dressed as a
measurement.
"""

from __future__ import annotations

from chainlens.exceptions import ChainlensError
from chainlens.models.enums import ClaimVerdict
from chainlens.providers.base import Provider
from chainlens.social.models import Post
from chainlens.verify.checks import (
    DEFAULT_SCAN_LIMIT,
    DEFAULT_TRANSFER_LIMIT,
    CheckContext,
    CheckerRegistry,
    default_registry,
)
from chainlens.verify.checks.base import CheckOutcome
from chainlens.verify.claims import ClaimElements
from chainlens.verify.likelihood import LikelihoodRatio, evaluate_likelihood
from chainlens.verify.parsing import ParsedClaim, parse_claim
from chainlens.verify.scale import DEFAULT_THRESHOLDS, VerbalThresholds
from chainlens.verify.schema import Claim, Extraction, validate_quotes
from chainlens.verify.verdicts import (
    STANDARD_VERIFICATION_LIMITATIONS,
    ClaimEvidence,
    CoincidenceEstimator,
    VerificationFinding,
    VerificationReport,
)

__all__ = ["VerificationEngine"]

#: The tolerance sweep, as multiples of the claim's own stated tolerance. The first
#: entry is the claim's own precision; the rest are the question "what if the post
#: meant something looser by *approximately* than we assumed?"
_TOLERANCE_VARIANTS: dict[str, float] = {
    "claim's own tolerance": 1.0,
    "tighter": 0.5,
    "looser": 2.0,
    "much looser": 10.0,
}


class VerificationEngine:
    """Adjudicates claims from one post against one provider.

    Args:
        provider: the chain data source.
        estimator: supplies the coincidence probability, when one is configured. The
            default is ``None``: no ratio is then reported and every finding says
            why. See :class:`~chainlens.verify.verdicts.CoincidenceEstimator`.
        registry: the claim-type to checker mapping. Defaults to the shipped
            checkers; pass a copy to add one for a single run.
        scan_limit: how many transactions to walk before declaring a scan truncated.
        transfer_limit: how many transfers to carry into a finding's evidence.
        thresholds: the verbal-scale boundaries. ENFSI-aligned by default, and
            configurable because the guideline treats the scale as
            jurisdiction-dependent.
    """

    def __init__(
        self,
        provider: Provider,
        *,
        estimator: CoincidenceEstimator | None = None,
        registry: CheckerRegistry | None = None,
        scan_limit: int = DEFAULT_SCAN_LIMIT,
        transfer_limit: int = DEFAULT_TRANSFER_LIMIT,
        thresholds: VerbalThresholds = DEFAULT_THRESHOLDS,
    ) -> None:
        self._provider = provider
        self._estimator = estimator
        self._registry = registry if registry is not None else default_registry()
        self._scan_limit = scan_limit
        self._transfer_limit = transfer_limit
        self._thresholds = thresholds

    @property
    def provider(self) -> Provider:
        """The provider claims are checked against."""
        return self._provider

    async def verify_post(self, post: Post, extraction: Extraction) -> VerificationReport:
        """Adjudicate every claim in ``extraction``, in the order they appear.

        Claims are also validated against the post first: a claim whose quote is not
        in the post is dropped rather than answered, and the drop is reported. A
        dropped claim is a statement about the extraction, and letting one through
        would mean publishing a verdict about something the post never said.
        """
        sources = (post.text, *(item.alt_text or "" for item in post.media))
        validation = validate_quotes(extraction, *sources)

        warnings: list[str] = []
        if validation.dropped:
            warnings.append(
                f"{validation.dropped_count} of {len(extraction.claims)} claims were "
                "dropped because their quotes are not in the post; a claim that cannot be "
                "tied to what the post said is not answered here"
            )
        if extraction.claims and not validation.kept:
            warnings.append(
                "every extracted claim was dropped, so no verdict in this report is about "
                "anything the post is known to have said"
            )

        findings = [await self.verify_claim(claim, post) for claim in validation.extraction.claims]

        return VerificationReport(
            post_id=post.id,
            provenance_strength=post.source.strength,
            findings=tuple(findings),
            warnings=tuple(warnings),
            limitations=STANDARD_VERIFICATION_LIMITATIONS,
        )

    async def verify_claim(self, claim: Claim, post: Post) -> VerificationFinding:
        """Adjudicate one claim, and attach a ratio only where one is justified."""
        parsed = parse_claim(claim)
        outcome = await self._dispatch(claim, parsed)

        likelihood, ratio_reason = await self._ratio_for(outcome, parsed.elements)

        return VerificationFinding(
            post_id=post.id,
            provenance_strength=post.source.strength,
            claim=claim,
            verdict=outcome.verdict,
            method=outcome.method,
            reason=outcome.reason or ratio_reason,
            elements=parsed.elements,
            evidence=outcome.evidence,
            likelihood=likelihood,
            assumptions=tuple(outcome.assumptions) + tuple(parsed.notes),
            caveats=outcome.caveats,
        )

    # -- internals -----------------------------------------------------------

    async def _dispatch(self, claim: Claim, parsed: ParsedClaim) -> CheckOutcome:
        """Route one claim to its checker, or explain why nothing ran."""
        checker = self._registry.for_type(claim.type)
        if checker is None:
            return CheckOutcome(
                verdict=ClaimVerdict.UNVERIFIABLE,
                method="none",
                evidence=ClaimEvidence(provider=self._provider.name),
                reason=(
                    f"no method exists here for a {claim.type.value!r} claim; this is not "
                    "a statement that the claim is false"
                ),
            )

        if checker.needs_elements and not parsed.is_priceable:
            return CheckOutcome(
                verdict=ClaimVerdict.INSUFFICIENT_DATA,
                method=checker.method,
                evidence=ClaimEvidence(provider=self._provider.name),
                reason=(
                    "the claim could not be reduced to elements that can be checked: "
                    + "; ".join(parsed.notes)
                ),
                caveats=(
                    "a claim we could not read is reported as short of data rather than as "
                    "false, because the failure is in the parsing and not in the chain",
                ),
            )

        context = CheckContext(
            provider=self._provider,
            claim=claim,
            elements=parsed.elements,
            scan_limit=self._scan_limit,
            transfer_limit=self._transfer_limit,
        )
        try:
            return await checker.run(context)
        except ChainlensError as exc:
            # A provider failure is a finding about *this run*, not about the claim:
            # reporting it as a contradiction would blame the chain for our outage.
            return CheckOutcome(
                verdict=ClaimVerdict.INSUFFICIENT_DATA,
                method=checker.method,
                evidence=ClaimEvidence(provider=self._provider.name),
                reason=f"the check did not complete: {exc}",
                caveats=("a failed lookup is not evidence for or against the claim",),
            )

    async def _ratio_for(
        self, outcome: CheckOutcome, elements: ClaimElements | None
    ) -> tuple[LikelihoodRatio | None, str | None]:
        """Compute the ratio, or say precisely why there is not one.

        The order of the refusals is deliberate — each is checked before the one it
        would make meaningless, so the reason reported is the *root* one. A scan
        that was both truncated and uncounted should say it was truncated, because
        the count is not a count of anything trustworthy.
        """
        if outcome.verdict is not ClaimVerdict.SUPPORTED:
            # No explanation is owed here: the checker already said why it reached this
            # verdict, and a ratio is not merely absent for a contradicted claim — it is
            # unavailable in principle, since the ratio is never below 1.
            return None, None
        if elements is None:
            return None, "the claim reduced to nothing that could be priced"
        if outcome.evidence.scan_complete is False:
            return None, (
                "the scan was not exhaustive, so the count of the sender's transfers is a "
                "lower bound and would inflate the ratio"
            )
        candidates = outcome.evidence.candidates_considered
        if candidates is None or candidates <= 0:
            return None, (
                "the sender made no transfers in the window, so there was no opportunity "
                "for a coincidence and nothing to price"
            )
        if self._estimator is None:
            return None, (
                "no coincidence estimator is configured, so the probability of a chance "
                "match cannot be estimated from data; the ratio is withheld rather than "
                "computed from an assumed rate"
            )

        estimate = await self._estimator.estimate(elements, provider=self._provider)
        if estimate is None:
            return None, (
                "the coincidence rate could not be estimated from the data available: the "
                "sample is too thin to price a match of this shape"
            )

        # The tolerance sweep is priced by the estimator, one variant at a time.
        #
        # `sensitivity_report`'s `variants` are alternative *probabilities* — each becomes
        # `Sweep(name=f"p:{name}")` and is fed straight to `likelihood_ratio` — so passing a
        # tolerance in base units crashed `coincidence_probability`'s range check. It went
        # unnoticed because the only test that reached this line used an exactly-stated
        # amount, whose tolerance is zero and whose variants were therefore all zero: a
        # sweep that varied nothing and passed. A hedged claim is the case the sweep exists
        # for, and it is the case that broke.
        #
        # Re-pricing is the estimator's job and cannot be the engine's: how much a wider
        # band raises the coincidence rate depends on the sample it was drawn from.
        variants = await self._tolerance_variants(elements)
        ratio = evaluate_likelihood(
            k=candidates,
            component=estimate.component,
            null_model=estimate.null_model,
            variants=variants,
            k_permutations=(max(0, candidates - 1), candidates + 1),
            thresholds=self._thresholds,
            provenance=outcome.evidence.provenance,
        )
        return ratio, None

    async def _tolerance_variants(self, elements: ClaimElements) -> dict[str, float] | None:
        """Price each tolerance variant, so the sweep varies a probability.

        The first variant is the claim's own band, which re-prices to the estimate already
        computed; it is kept because the sweep is reported as a list and a reader expects
        the claim's own tolerance to appear among the alternatives rather than to be
        silently the baseline.
        """
        band = elements.band
        if band is None or self._estimator is None:
            return None
        if band.tolerance == 0 and not band.at_least:
            # Nothing to vary. Four identical variants would be reported as four sweeps,
            # which reads as "the tolerance was tested and it did not matter" when in fact
            # no tolerance was stated. A one-sided band is the exception: its tolerance is
            # zero but widening the band still opens it further.
            return None

        variants: dict[str, float] = {}
        for name, factor in _TOLERANCE_VARIANTS.items():
            scaled = elements.model_copy(update={"band": band.scaled(factor)})
            priced = await self._estimator.estimate(scaled, provider=self._provider)
            if priced is not None:
                variants[name] = priced.component.value
        return variants or None
