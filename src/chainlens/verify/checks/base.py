"""What a checker is given, and what it is allowed to return.

The verifiers are plain async functions rather than classes, and they are
registered by the claim type they handle. The reason is that a checker has no
state worth keeping: it reads chain data, compares it with a parsed claim, and
answers. A class here would exist only to hold a provider that the context already
carries.

What a checker may **not** do is as much the point as what it may. It cannot
produce a likelihood ratio — the mathematics lives in
:mod:`chainlens.verify.likelihood` and the assembly in the engine, so no checker
can invent a number by accident — and it cannot see the model's own confidence in
its extraction, because that self-report must never reach a computation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import Field, model_validator

from chainlens.models.base import LensModel
from chainlens.models.calculation import Binding, Input, UnboundKind
from chainlens.models.enums import ClaimVerdict
from chainlens.providers.base import Provider
from chainlens.verify.claims import ClaimElements
from chainlens.verify.schema import Claim, ClaimType
from chainlens.verify.verdicts import ClaimEvidence

__all__ = [
    "DEFAULT_SCAN_LIMIT",
    "DEFAULT_TRANSFER_LIMIT",
    "CheckContext",
    "CheckOutcome",
    "Checker",
    "CheckerRegistry",
    "drain",
]

T = TypeVar("T")

#: How many of the sender's transactions the engine will walk before declaring the
#: scan truncated. A claim about a busy exchange address is not one this machinery
#: can price, and saying so is better than walking a million transactions to find
#: out that it could have.
DEFAULT_SCAN_LIMIT = 2_000

#: How many transfers one finding will carry in its evidence. The cap is reported
#: when it is hit: a partial list that looks complete is worse than a short one
#: that says it is short.
DEFAULT_TRANSFER_LIMIT = 50


@dataclass(frozen=True, slots=True)
class CheckContext:
    """Everything a checker is allowed to use.

    Attributes:
        provider: the provider to ask.
        claim: the claim as extracted, for its type, its identifiers and its quote.
        elements: the claim reduced to what can be priced, or ``None`` when it did
            not reduce. A checker that can work without them — one keyed on a
            transaction id, or on an asserted label — is handed ``None`` and runs
            anyway; the rest ask for :attr:`needs`.
        scan_limit: how many transactions to walk before declaring the scan
            truncated.
        transfer_limit: how many transfers to carry into the evidence.
    """

    provider: Provider
    claim: Claim
    elements: ClaimElements | None = None
    scan_limit: int = DEFAULT_SCAN_LIMIT
    transfer_limit: int = DEFAULT_TRANSFER_LIMIT

    @property
    def needs(self) -> ClaimElements:
        """The parsed elements, for a checker that cannot run without them.

        Raises:
            ValueError: when the claim did not reduce to anything priceable. The
                engine does not dispatch such a claim to a checker that needs
                elements, so reaching this is a programming error rather than a
                condition in the data — and it should fail loudly rather than be
                answered with a verdict nobody computed.
        """
        if self.elements is None:
            raise ValueError(
                "this checker needs parsed elements and the engine must not have "
                "dispatched a claim that did not reduce to any"
            )
        return self.elements


def no_method_exists(reason: str) -> Input:
    """Nothing here could obtain the answer, and no configuration would create one.

    "I own this address" is not a question the chain answers, and an attribution label comes
    from a third party rather than from a ledger. Saying so is telling a reader to stop asking,
    which is why it is a different kind from the two below rather than a stronger version of
    them.
    """
    return _unanswered(UnboundKind.NO_METHOD, reason)


def not_reachable(reason: str) -> Input:
    """Something could obtain the answer, and this run's data or configuration did not.

    The actionable one: add a provider, widen the window, raise the budget. A reader who cannot
    tell this from :func:`no_method_exists` cannot tell a gap in their own setup from a limit of
    the chain, and the two want opposite things from them.
    """
    return _unanswered(UnboundKind.NO_DATA, reason)


def _unanswered(kind: UnboundKind, reason: str) -> Input:
    """The shape both of the above have: an input named for what is missing."""
    return Input(
        name="verdict",
        label="why nothing here answers the claim",
        binding=Binding.UNBOUND,
        kind=kind,
        reason=reason,
    )


class CheckOutcome(LensModel):
    """One checker's answer: a verdict, its evidence, and what it rests on.

    There is no likelihood-ratio field here on purpose. A checker that could
    attach a ratio would be a checker that could compute one, and the ratio has
    exactly one home — so the engine assembles it, from the ``k`` and the scan
    completeness this outcome reports.

    Attributes:
        verdict: the categorical finding.
        method: the checker's name, recorded in the finding.
        evidence: what the chain showed.
        gap: why the claim was not resolved, when it was not — the unbound input the
            verdict rests on. Carries its kind, so the three ways of not answering are
            told apart by a machine and not only by a phrasing.
        assumptions: what the result rests on, including every convention applied.
        caveats: what would change it.
    """

    verdict: ClaimVerdict
    method: str
    evidence: ClaimEvidence = Field(default_factory=lambda: ClaimEvidence())
    reason: str | None = None
    gap: Input | None = None
    assumptions: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _an_unresolved_claim_says_what_is_missing(self) -> CheckOutcome:
        """Refuse an unresolved verdict with nothing saying why.

        This is the invariant that replaced "the verdict names the kind". There is one verdict
        for not having decided, so the thing that must not be absent is the *reason* — a finding
        that came out unresolved with no gap is a reader being told nothing at all, which is the
        state the whole vocabulary exists to make unrepresentable.
        """
        if self.verdict is ClaimVerdict.UNRESOLVED and self.gap is None:
            raise ValueError(
                "a claim that was not resolved must carry the input it is missing; "
                "otherwise there is nothing telling a reader whether to stop asking or to "
                "configure something"
            )
        return self

    @property
    def explanation(self) -> str | None:
        """What this outcome owes a reader, from whichever field carries it.

        Two sources, because they are two different statements. An unresolved claim explains
        *what is missing*, and the words belong to the input that has no value. A decided one
        may explain *why it came out that way* — a contradiction whose asserted labels none of
        the source's labels match — and that is not a gap but the finding's own reasoning.
        """
        if self.reason is not None:
            return self.reason
        return self.gap.reason if self.gap is not None else None


@dataclass(frozen=True, slots=True)
class Checker:
    """One claim type's handler, and what it needs in order to run.

    Attributes:
        method: the checker's name, recorded in every finding it produces.
        run: the coroutine that adjudicates the claim.
        needs_elements: whether the claim must have reduced to priceable elements
            first. A checker keyed on a transaction id or an asserted label needs no
            addresses, and refusing those claims for want of elements would turn
            "we could not read this post" into "we cannot answer this question" —
            which are different findings with different remedies.
    """

    method: str
    run: Callable[[CheckContext], Awaitable[CheckOutcome]]
    needs_elements: bool = True


async def drain(stream: AsyncIterator[T], *, limit: int) -> tuple[tuple[T, ...], bool]:
    """Read at most ``limit`` items, reporting whether more were waiting.

    One item past the limit is *observed* rather than assumed, so a stream that
    happened to hold exactly ``limit`` items and no more is reported as complete —
    calling it truncated would refuse results that are perfectly well founded.

    The stream is closed explicitly when it can be. The provider protocol promises
    an ``AsyncIterator`` rather than an ``AsyncGenerator``, so ``aclose`` is not
    guaranteed; but an abandoned generator can hold a response body open until the
    garbage collector reaches it, so it is closed whenever it is there.
    """
    seen: list[T] = []
    truncated = False
    try:
        async for item in stream:
            if len(seen) >= limit:
                truncated = True
                break
            seen.append(item)
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()
    return tuple(seen), truncated


@dataclass
class CheckerRegistry:
    """Which checker answers which claim type.

    An object holding a dict rather than a module-level dict, so a caller can take
    a copy and add a checker for one run without changing what the library does for
    everyone else.
    """

    checkers: dict[ClaimType, Checker] = field(default_factory=dict)

    def register(self, claim_type: ClaimType, checker: Checker) -> None:
        """Bind ``checker`` to ``claim_type``, replacing any previous binding."""
        self.checkers[claim_type] = checker

    def for_type(self, claim_type: ClaimType) -> Checker | None:
        """The checker for ``claim_type``, if this library has one."""
        return self.checkers.get(claim_type)

    def copy(self) -> CheckerRegistry:
        """A mutable copy, so a caller can extend the set for one run."""
        return CheckerRegistry(checkers=dict(self.checkers))
