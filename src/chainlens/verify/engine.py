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
from one.

**Where there is no ratio, there is still the calculation.** Every finding carries a
:class:`~chainlens.models.calculation.RatioAttempt` — the inputs with their bindings and
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
"""

from __future__ import annotations

import math

from chainlens.exceptions import ChainlensError
from chainlens.models.calculation import (
    Binding,
    BoundDirection,
    Input,
    Operation,
    OperationKind,
    RatioAttempt,
    Source,
    SourceKind,
    UnboundKind,
)
from chainlens.models.enums import ClaimVerdict
from chainlens.models.selection import SelectionDisclosure
from chainlens.models.wire import detail_entries
from chainlens.providers.base import Provider
from chainlens.social.models import Post
from chainlens.verify.checks import (
    DEFAULT_SCAN_LIMIT,
    DEFAULT_TRANSFER_LIMIT,
    CheckContext,
    CheckerRegistry,
    default_registry,
)
from chainlens.verify.checks.base import CheckOutcome, no_method_exists, not_reachable
from chainlens.verify.claims import ClaimElements
from chainlens.verify.likelihood import LikelihoodRatio, evaluate_likelihood, formula_for
from chainlens.verify.parsing import ParsedClaim, parse_claim
from chainlens.verify.scale import DEFAULT_THRESHOLDS, VerbalThresholds
from chainlens.verify.schema import Claim, Extraction, validate_quotes
from chainlens.verify.verdicts import (
    STANDARD_VERIFICATION_LIMITATIONS,
    ClaimEvidence,
    CoincidenceEstimator,
    RateEstimate,
    Unpriced,
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


def _ratio_operation(k: Input, p: Input, ratio: LikelihoodRatio | None) -> Operation:
    """The arithmetic, with its result when every input was exact and its reason when not.

    A withheld ratio names the input that stopped it, because "no ratio was reported" is not
    something a reader can act on and "``k`` is a lower bound, so this would be an upper
    estimate" is. The reason lives here rather than on the input because an input that *has* a
    value has nothing to explain — a lower bound is a value, bounded.
    """
    return Operation(
        kind=OperationKind.LIKELIHOOD_RATIO,
        formula=formula_for(OperationKind.LIKELIHOOD_RATIO),
        inputs=(k.name, p.name),
        result=ratio.lr if ratio is not None else None,
        direction=(
            BoundDirection.LOWER
            if ratio is not None and math.isinf(ratio.lr)
            else BoundDirection.POINT
        ),
        reason=None if ratio is not None else _why_withheld(k, p),
    )


def _selection_caveats(selection: SelectionDisclosure | None) -> tuple[str, ...]:
    """What a finding has to say about how its claim was chosen, and whether it was transcribed.

    Two caveats rather than one, because a claim can be chosen by nobody and still rest on a model's
    reading of a screenshot, and it can be chosen by a model and rest on a PDF. A reader weighing a
    number needs to be able to tell which of the two applies — collapsing them into one sentence
    would make "this was picked" and "this was read by a model" look like the same fact.
    """
    if selection is None:
        return ()
    notes = [selection.limitation]
    if (transcription := selection.transcription_note) is not None:
        notes.append(transcription)
    return tuple(notes)


def _unbound_input(attempt: RatioAttempt | None) -> Input | None:
    """The first input an attempt could not obtain, if it could not obtain one.

    First rather than all, because a finding turns on one thing: an unbound ``p`` says nothing
    about whether ``k`` was counted, and the input that stopped the arithmetic is the one a
    reader has to deal with.
    """
    if attempt is None:
        return None
    return next((item for item in attempt.inputs if item.binding is Binding.UNBOUND), None)


def _withheld_reason(attempt: RatioAttempt | None) -> str | None:
    """The one sentence a reader gets today, taken from the calculation that replaces it.

    Temporary. The derivation builder and three tests still read ``finding.reason``, so it is
    derived from the attempt rather than left to be filled in twice. It disappears when the
    builder renders the inputs — a ratio with a hole in it has one reason per hole, and this
    flattens several into one.
    """
    if attempt is None or attempt.operation is None:
        return None
    return attempt.operation.reason


def _why_withheld(k: Input, p: Input) -> str:
    """Which input stopped the arithmetic, and what that means for a reader.

    Ordered by root cause rather than by field: a count that was never made is a different
    failure from a count that was made and came up short, and a sender with no movements is a
    different finding from a scan that did not finish looking.
    """
    if k.binding is Binding.UNBOUND:
        return k.reason  # type: ignore[return-value]  # an unbound input always carries one
    if k.direction is not BoundDirection.POINT:
        return (
            "the scan was not exhaustive, so the count of the sender's transfers is a lower "
            "bound and would inflate the ratio"
        )
    if k.value == 0:
        return (
            "the sender made no transfers in the window, so there was no opportunity for a "
            "coincidence and nothing to price"
        )
    return p.reason  # type: ignore[return-value]  # unbound, and unbound always reasons


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
        estimate_requested: whether anybody wanted a coincidence priced. Says nothing about
            whether one *could* be: with no estimator, this field is the difference between a
            caller who decided against it and a setup that never had one, and the two read
            differently on an artifact because they are fixed differently.
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
        estimate_requested: bool = True,
        selection: SelectionDisclosure | None = None,
    ) -> None:
        self._provider = provider
        self._estimator = estimator
        #: Whether anybody wanted a coincidence priced at all. Without this the engine cannot
        #: tell "the caller said not to" from "nobody configured an estimator", which are the
        #: same `None` and want opposite things from a reader — one is a decision, the other a
        #: gap in the setup. `ui derive --no-estimate` is the caller that says not to.
        self._estimate_requested = estimate_requested
        self._registry = registry if registry is not None else default_registry()
        self._scan_limit = scan_limit
        self._transfer_limit = transfer_limit
        self._thresholds = thresholds
        #: How the claims reached this engine, when a chooser picked them. Stamped on every
        #: finding and added to its caveats, because the alternative — carrying it on the batch —
        #: lets a finding travel on its own with a ratio that reads as pre-registered.
        self._selection = selection

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

        likelihood, attempt = await self._ratio_for(outcome, parsed.elements)
        # The checker's own gap when it could not answer, and otherwise the input that
        # stopped the arithmetic. One field for both, because "the claim could not be
        # resolved" and "no number could be computed" are the same shape: something the
        # finding turns on has no value, and it says which kind of missing it is.
        gap = outcome.gap or _unbound_input(attempt)

        return VerificationFinding(
            post_id=post.id,
            provenance_strength=post.source.strength,
            claim=claim,
            verdict=outcome.verdict,
            method=outcome.method,
            # Derived from the attempt while the derivation builder is migrated: `reason` is
            # one sentence where an attempt has several inputs, and the sentence a reader gets
            # is the one about the input that stopped it. This goes when nothing reads it.
            reason=outcome.explanation or _withheld_reason(attempt),
            elements=parsed.elements,
            evidence=outcome.evidence,
            likelihood=likelihood,
            attempt=attempt,
            gap=gap,
            assumptions=tuple(outcome.assumptions) + tuple(parsed.notes),
            caveats=outcome.caveats + _selection_caveats(self._selection),
            selection=self._selection,
        )

    # -- internals -----------------------------------------------------------

    async def _dispatch(self, claim: Claim, parsed: ParsedClaim) -> CheckOutcome:
        """Route one claim to its checker, or explain why nothing ran."""
        checker = self._registry.for_type(claim.type)
        if checker is None:
            return CheckOutcome(
                verdict=ClaimVerdict.UNRESOLVED,
                method="none",
                evidence=ClaimEvidence(provider=self._provider.name),
                gap=no_method_exists(
                    f"no method exists here for a {claim.type.value!r} claim; this is not "
                    "a statement that the claim is false"
                ),
            )

        if checker.needs_elements and not parsed.is_priceable:
            return CheckOutcome(
                verdict=ClaimVerdict.UNRESOLVED,
                method=checker.method,
                evidence=ClaimEvidence(provider=self._provider.name),
                gap=not_reachable(
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
                verdict=ClaimVerdict.UNRESOLVED,
                method=checker.method,
                evidence=ClaimEvidence(provider=self._provider.name),
                gap=not_reachable(f"the check did not complete: {exc}"),
                caveats=("a failed lookup is not evidence for or against the claim",),
            )

    async def _ratio_for(
        self, outcome: CheckOutcome, elements: ClaimElements | None
    ) -> tuple[LikelihoodRatio | None, RatioAttempt | None]:
        """Price the coincidence, or build the calculation that would have priced it.

        The order is deliberate — each condition is checked before the one it would make
        meaningless, so a hole is reported at its root. A scan that was both truncated and
        uncounted says it was truncated, because the count is not a count of anything
        trustworthy.

        Returns the ratio **and** the attempt rather than one instead of the other, because a
        ratio a reader cannot check is the artifact this design exists to avoid. When an input
        is one-sided or unbound the ratio is ``None`` and the attempt still carries the
        formula, the inputs and where the reasoning stopped.
        """
        if outcome.verdict is not ClaimVerdict.SUPPORTED:
            # Not a withheld number but an unavailable one: a ratio is never below 1, so a
            # contradicted claim has no argument of this shape to make.
            return None, None
        if elements is None:
            # Nothing priceable, so there is no k/p-shaped calculation to show at all.
            return None, None

        k = self._count_input(outcome.evidence)
        p, estimate = await self._rate_input(elements)

        ratio: LikelihoodRatio | None = None
        # Every input exact is not sufficient: the operation also has a domain. A sender with no
        # movements in the window gives `k = 0`, which is a genuine value and not a missing one,
        # and `1 / (1 - (1 - p) ** 0)` is 1 — no evidence dressed as a number. `evaluate_likelihood`
        # refuses it, and the refusal belongs on the operation rather than on the input: nothing
        # is unknown here, the question simply has no answer of this shape.
        if k.is_exact and k.value and estimate is not None:
            candidates = outcome.evidence.candidates_considered
            assert candidates is not None  # an exact k means it was counted
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

        return ratio, RatioAttempt(inputs=(k, p), operation=_ratio_operation(k, p, ratio))

    def _count_input(self, evidence: ClaimEvidence) -> Input:
        """``k``: how many chances the sender gave for a coincidence.

        A truncated scan does not leave this unbound — it bounds it from below, which is the
        honest reading and the one that stops the ratio being computed. The direction carries
        that, so nothing else on the artifact has to.
        """
        candidates = evidence.candidates_considered
        source = Source(
            kind=SourceKind.COUNTED,
            text="the sender's movements inside the claim's window",
        )
        if candidates is None:
            return Input(
                name="k",
                label="opportunities for a coincidence",
                binding=Binding.UNBOUND,
                kind=UnboundKind.NO_DATA,
                reason=(
                    "the sender's movements in the window were not counted, so there is no "
                    "number of opportunities to price"
                ),
            )
        return Input(
            name="k",
            label="opportunities for a coincidence",
            binding=Binding.BOUND,
            value=float(candidates),
            unit="movements",
            direction=(
                BoundDirection.POINT
                if evidence.scan_complete is not False
                else BoundDirection.LOWER
            ),
            source=source,
            detail=detail_entries({"candidates_considered": candidates}),
        )

    async def _rate_input(self, elements: ClaimElements) -> tuple[Input, RateEstimate | None]:
        """``p``: the chance that one of those chances matches by coincidence.

        Four ways this comes back without a value, and the kind is what tells them apart. The
        estimator declining and the estimator having too little to work with are both
        ``no_data`` and differ only in whether it could say why — a distinction a reader never
        needed, and one that used to be carried by two different return types. Whether anyone
        asked at all is the third, and it is the caller's to state.

        Returns the estimate alongside the input so that the caller does not draw a second
        sample for the same finding: one coincidence attempt, one estimate.
        """
        label = "chance of a coincidental match"
        if self._estimator is None:
            asked_for = self._estimate_requested
            return (
                Input(
                    name="p",
                    label=label,
                    binding=Binding.UNBOUND,
                    kind=(UnboundKind.NO_DATA if asked_for else UnboundKind.NOT_REQUESTED),
                    reason=(
                        "no coincidence estimator is configured, so the probability of a "
                        "chance match cannot be estimated from data; the ratio is withheld "
                        "rather than computed from an assumed rate"
                        if asked_for
                        else "pricing was not asked for, so this run carries no ratio — which "
                        "is what a document that must not change with a sample is for"
                    ),
                ),
                None,
            )

        estimate = await self._estimator.estimate(elements, provider=self._provider)
        if estimate is None:
            return (
                Input(
                    name="p",
                    label=label,
                    binding=Binding.UNBOUND,
                    kind=UnboundKind.NO_DATA,
                    reason=(
                        "the coincidence rate could not be estimated from the data available: "
                        "the sample is too thin to price a match of this shape"
                    ),
                ),
                None,
            )
        if isinstance(estimate, Unpriced):
            # The estimator's own words and its own kind, verbatim: it is the only thing that
            # knows which precondition failed, and whether that precondition is a limit of the
            # data or a limit of the method is the part a reader acts on.
            return (
                Input(
                    name="p",
                    label=label,
                    binding=Binding.UNBOUND,
                    kind=estimate.kind,
                    reason=estimate.reason,
                ),
                None,
            )

        component = estimate.component
        return (
            Input(
                name="p",
                label=label,
                binding=Binding.BOUND,
                value=component.value,
                direction=(
                    BoundDirection.UPPER if component.is_upper_bound else BoundDirection.POINT
                ),
                source=Source(kind=SourceKind.ESTIMATED, text=component.population),
                detail=detail_entries(
                    {
                        "successes": component.successes,
                        "trials": component.trials,
                        "ci_lower": component.ci_lower,
                        "ci_upper": component.ci_upper,
                        "method": component.method.value,
                        "null_model": estimate.null_model.value,
                    }
                ),
            ),
            estimate,
        )

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
            # A refusal is not a variant: reporting a sweep step the estimator would not price
            # would put a number in the envelope that nothing stands behind.
            if isinstance(priced, RateEstimate):
                variants[name] = priced.component.value
        return variants or None
