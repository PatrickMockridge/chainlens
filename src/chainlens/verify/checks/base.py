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


def unanswered(kind: UnboundKind, reason: str) -> Input:
    """Why a claim has no verdict, as the input that has no value.

    A checker that cannot answer is saying one thing: the claim's answer is an input it did
    not obtain. Making that an :class:`Input` rather than a sentence is what lets a reader
    tell *which* kind of missing it is — nothing here could obtain it, something could and
    the data was not reachable, or nobody asked — without reading the prose.
    """
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
    def _the_verdict_names_the_kind(self) -> CheckOutcome:
        """Turn a refusal into the input that has no value, typed by the verdict.

        The two unanswerable verdicts *are* the two kinds — the module docstring of
        :mod:`chainlens.verify.verdicts` has argued it since before this vocabulary existed,
        because "stop asking" and "configure something" are different instructions. Deriving
        the kind here rather than at each of the nineteen refusals means the two cannot drift
        apart: a checker that says `UNVERIFIABLE` and a checker that says `no_data` would be
        saying incompatible things, and there is one place that decides which.
        """
        if self.reason is None or self.gap is not None:
            return self
        kind = (
            UnboundKind.NO_METHOD
            if self.verdict is ClaimVerdict.UNVERIFIABLE
            else UnboundKind.NO_DATA
        )
        object.__setattr__(self, "gap", unanswered(kind, self.reason))
        return self


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
