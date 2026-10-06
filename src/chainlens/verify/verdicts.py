"""What the chain showed, what it is worth, and the line between them.

The verdict rule, stated once so no checker has to re-derive it:

============================  ==================================================
:attr:`ClaimVerdict`           when
============================  ==================================================
``SUPPORTED``                 chain data is consistent with the claim
``CONTRADICTED``              chain data rules it out, including an identifier
                              that does not exist
``UNVERIFIABLE``              **no method exists** for this class of claim, so
                              its veracity is not a question chain data answers
``INSUFFICIENT_DATA``         a method exists and the data it needs is missing
============================  ==================================================

The split that earns its keep is the last two, because they look identical in a
report and mean opposite things to a reader. ``UNVERIFIABLE`` says *stop asking*:
"I own this address" is not a claim about the ledger, and attribution labels come
from a third party rather than from the chain, so with no label source configured
there is no method here — not a missing datum. ``INSUFFICIENT_DATA`` says
*configure something*: a transfer claim against a provider that cannot list an
address's transactions is answerable in principle and blocked in practice, and the
reader can fix it.

Collapsing them into one "unknown" would hide both the reason and the remedy, which
is why they are separate enum members and why every finding carries a
machine-readable ``reason`` next to the verdict rather than leaving a reader to
infer one from prose.

The other line this module holds: **the verdict and the likelihood ratio are
independent.** The verdict is computed from chain data; the ratio is attached to
it, never derived from it. A ratio of 500 does not make anything ``SUPPORTED``,
and nothing here can promote a ``CONTRADICTED`` claim — the ratio is mathematically
never below 1, so a contradicted claim can never carry one at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import Field

from chainlens.models.base import LensModel, Provenance
from chainlens.models.calculation import Input, RatioAttempt, UnboundKind
from chainlens.models.enums import ClaimVerdict
from chainlens.models.primitives import Transfer
from chainlens.providers.base import Provider
from chainlens.social.models import ProvenanceStrength
from chainlens.verify.claims import ClaimElements
from chainlens.verify.likelihood import ComponentEstimate, LikelihoodRatio, NullModel
from chainlens.verify.schema import Claim

__all__ = [
    "STANDARD_VERIFICATION_LIMITATIONS",
    "ClaimEvidence",
    "CoincidenceEstimator",
    "RateEstimate",
    "Unpriced",
    "VerificationFinding",
    "VerificationReport",
]

#: The standing caveats, carried on every finding and every derivation.
#:
#: **The third selection case is named even though no agent ships.** The text used to run
#: "a forensic ratio is computed for a proposition chosen without regard to the evidence, and a
#: claim harvested from a post was not" — a list of two, written as though it were the whole list.
#: It is not: a proposition chosen *after* a finding was seen was chosen with the evidence in view,
#: and that is reachable without any loop in this library — whoever runs an extract over a post and
#: then adjudicates the claim that looked interesting has done it. Naming it costs a clause and
#: makes the other two honest, because a list that reads as complete and is not is worse than no
#: list. It is also the sentence that would have to exist before any agentic mode could be argued
#: for at all, which is why it was written while estimating that mode rather than after building it.
STANDARD_VERIFICATION_LIMITATIONS = """\
A verdict is about the match structure, not about belief. SUPPORTED means the
chain data is consistent with the claim; it does not mean the post is honest, and
it cannot: the chain data inside a doctored screenshot is real regardless of
whether the post is.

A likelihood ratio, where one is reported, is the weight of the evidence for the
observed transfer being the *specific payment asserted* rather than a coincidental
one by the same sender. It is not the probability that the claim is true, and it
is not robust to how the claim was selected: a forensic ratio is computed for a
proposition chosen without regard to the evidence; a claim harvested from a post
was chosen before this tool saw it; and a claim chosen after a finding was seen was
chosen with the evidence in view. A number a chooser can improve by choosing is a
screen, not a weight.

UNVERIFIABLE means no method here exists for that class of claim -- it is not a
statement that the claim is false, and not a statement that it is true.
INSUFFICIENT_DATA means the class is checkable and the data was missing; the two
are reported separately because only one of them can be fixed.
"""


class ClaimEvidence(LensModel):
    """What the chain showed, and where every figure in it came from.

    An amount a reader cannot trace back to a transaction is an assertion rather
    than evidence, so the transfers themselves are carried rather than summarised
    into a total.

    Attributes:
        provider: which provider answered, when one did.
        endpoint: the endpoint or method, for a reader who wants to re-run it.
        txids: every transaction id the finding rests on.
        transfers: the movements found, capped at the engine's record limit.
        transfers_truncated: whether that cap was hit, so a partial list is never
            read as the whole of it.
        candidates_considered: ``k``, how many of the sender's own transfers were
            examined for a coincidence. ``None`` when the claim does not have that
            shape.
        scan_complete: whether the scan that produced ``k`` was exhausted. ``None``
            when no scan was involved. A ``False`` here is what forbids a ratio:
            an under-counted ``k`` inflates it.
        apportioned_shares: the inferred shares that matter to this outcome, keyed by
            edge key, and only where they disagree with a value the ledger recorded.
            On a match, the share of each matched output; on a contradiction, the
            shares that would have satisfied the claim when no recorded value did —
            the near-miss, reported so a reader can see which of two figures the
            chain wrote down. Never used to decide the verdict.
        detail: checker-specific facts a reviewer would want and no general field
            fits — a balance observed, a label asserted, a cluster size.
        provenance: one record per fetch, so a run can be replayed or audited.
        warnings: anything that qualified the check without changing the verdict.
    """

    provider: str | None = None
    endpoint: str | None = None

    txids: tuple[str, ...] = ()
    transfers: tuple[Transfer, ...] = ()
    transfers_truncated: bool = False
    apportioned_shares: Mapping[str, int] = Field(default_factory=dict)

    candidates_considered: int | None = Field(default=None, ge=0)
    scan_complete: bool | None = None

    detail: Mapping[str, Any] = Field(default_factory=dict)
    provenance: tuple[Provenance, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        """Whether this evidence supports nothing at all."""
        return not (self.txids or self.transfers or self.detail)


@dataclass(frozen=True, slots=True)
class RateEstimate:
    """A coincidence rate, and the null it was estimated under.

    The two travel together because the null model is a property of *how the sample
    was drawn*, not a label applied afterwards: a rate counted over the sender's own
    other transfers and a rate counted over the network at large answer different
    questions, and a bare float cannot say which one it is. Reporting the wrong null
    errs in a direction that depends on the claim — see the engine's docstring.

    Attributes:
        component: the estimated probability, with its sample size and interval.
        null_model: which coincidence mechanism the sample describes.
    """

    component: ComponentEstimate
    null_model: NullModel


@dataclass(frozen=True, slots=True)
class Unpriced:
    """A refusal to price, in the estimator's own words.

    ``None`` already means one thing: the sample the estimator could reach was too thin to price.
    This is for the refusals an estimator can *diagnose* — the claim names no window, the sender
    has nothing outside it to compare against, the null model needs a sample no provider can draw
    — where collapsing them into one generic sentence would hide the reason, and the reason is the
    part a caller can act on.

    Attributes:
        reason: what stopped it, phrased for the derivation's ``because`` node, which renders it
            verbatim.
        samples: how many movements the estimator got to look at, when it looked at any.
        kind: which of the three answers this refusal is. The estimator is the only thing that
            knows, and the difference is what a reader acts on: a claim with no window wants a
            window, a provider that cannot list movements wants a different provider, and the
            population null model wants a reader to stop asking, because no free provider
            enumerates a network-wide sample. Guessing ``no_data`` for all three would put a
            limit of the data on the same footing as a limit of the method.
    """

    reason: str
    samples: int | None = None
    kind: UnboundKind = UnboundKind.NO_DATA


class CoincidenceEstimator(Protocol):
    """Supplies the coincidence probability ``p`` for a claim's priced elements.

    The engine ships **no default implementation**, and that is the design rather
    than a gap. Estimating ``p`` needs transfers *in a window*, which a per-address
    provider cannot supply; the alternative would be a constant, and a constant
    would be an invented rate wearing a measurement's clothes. With no estimator
    configured, a finding simply carries no ratio and says why.

    An implementation returns ``None`` when the sample it can reach is too thin to
    price the coincidence, which is a normal answer for a rare recipient — and an
    :class:`Unpriced` when it can say *why* it will not price one, which the engine puts
    into the finding verbatim.
    """

    async def estimate(
        self, elements: ClaimElements, *, provider: Provider
    ) -> RateEstimate | Unpriced | None: ...


class VerificationFinding(LensModel):
    """One claim, adjudicated, with everything a reader needs to disagree.

    Attributes:
        post_id: the post the claim was read from.
        provenance_strength: how that post's content was obtained. Carried here as
            well as on the report because the two are genuinely independent: a
            chain claim in a hand-supplied screenshot can be ``SUPPORTED``, because
            the chain data is real whatever the post is, and stating the strength
            beside the verdict is the difference between an honest tool and one
            that launders a screenshot into a finding.
        claim: the claim as extracted, unchanged.
        verdict: the categorical finding.
        method: which checker produced it, so a reader can go and read that method.
        reason: the machine-readable explanation, always present when no ratio is
            reported and always present for the two unanswerable verdicts. **Being
            retired**: it is derived from :attr:`attempt` while the derivation builder is
            migrated, and disappears when nothing reads it.
        elements: what was priced, when the claim reduced to something priceable.
        evidence: what the chain showed.
        likelihood: the weight of the evidence, when it could be priced at all.
        attempt: what a ratio would have rested on, whether or not one was reported. The
            inputs with their bindings, and the operation with its formula — so a withheld
            ratio travels as a calculation with a hole in it rather than as a sentence.
        gap: the one unbound input this finding turns on, when it turns on one. A checker
            that could not answer says so here, and so does a ratio that was withheld because
            an input was missing — the two are the same shape, which is the point.
        assumptions: what the result rests on, including every convention applied.
        caveats: what would change it.
    """

    post_id: str
    provenance_strength: ProvenanceStrength

    claim: Claim
    verdict: ClaimVerdict
    method: str
    reason: str | None = None
    gap: Input | None = None

    elements: ClaimElements | None = None
    evidence: ClaimEvidence = Field(default_factory=lambda: ClaimEvidence())
    likelihood: LikelihoodRatio | None = None
    attempt: RatioAttempt | None = None

    assumptions: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()

    @property
    def is_informative(self) -> bool:
        """Whether the evidence distinguishes anything at all.

        False for the two verdicts that mean "no answer", which a caller rendering
        a table needs to tell apart from a finding that went one way or the other.
        """
        return self.verdict in {ClaimVerdict.SUPPORTED, ClaimVerdict.CONTRADICTED}

    @property
    def has_ratio(self) -> bool:
        """Whether a likelihood ratio was reported."""
        return self.likelihood is not None


class VerificationReport(LensModel):
    """Every claim in one post, and the frame they should be read in.

    Attributes:
        post_id: the post the findings were read from.
        provenance_strength: how the post's content was obtained.
        findings: one per claim, including the ones that could not be checked.
        warnings: post-level problems — dropped claims, unreadable media, an
            extraction that produced nothing.
        limitations: the standing caveats, carried on the artifact rather than in
            a README, because a number without its caveats travels badly.
    """

    post_id: str
    provenance_strength: ProvenanceStrength
    findings: tuple[VerificationFinding, ...] = ()
    warnings: tuple[str, ...] = ()
    limitations: str = STANDARD_VERIFICATION_LIMITATIONS

    @property
    def counts(self) -> Mapping[ClaimVerdict, int]:
        """How many findings landed on each verdict, including the zeroes.

        Every member is present, so a caller can render a fixed set of rows and a
        missing verdict reads as zero rather than as a missing key.
        """
        return {
            verdict: sum(1 for finding in self.findings if finding.verdict is verdict)
            for verdict in ClaimVerdict
        }

    @property
    def is_informative(self) -> bool:
        """Whether any finding actually decided anything."""
        return any(finding.is_informative for finding in self.findings)

    @property
    def with_ratio(self) -> tuple[VerificationFinding, ...]:
        """The findings that carry a likelihood ratio."""
        return tuple(finding for finding in self.findings if finding.has_ratio)

    def __len__(self) -> int:
        return len(self.findings)
