"""A claim reduced to the elements that can actually be priced.

Before any probability can be computed, a sentence has to become a set of
checkable elements: which chain, which asset, which sender, and optionally a
recipient, an amount with a tolerance, and a window.

The amount tolerance is not a detail. It is the single largest free parameter in
the whole calculation — it comes from an extraction's reading of a word like
"approximately" — and it moves the likelihood ratio roughly linearly. It is a
first-class field here, and the sensitivity analysis sweeps it, precisely so that
its influence is visible rather than hidden inside a parser.
"""

from __future__ import annotations

import math
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from chainlens.models.base import LensModel
from chainlens.models.enums import Chain
from chainlens.models.primitives import AssetRef

__all__ = ["ActivityWindow", "AmountBand", "ClaimElements"]


class AmountBand(LensModel):
    """An amount and how far from it the claim would still be counting.

    In integer base units, like every other amount in the library — a float here
    would be a way for 0.1 BTC to become 0.09999999999.

    Attributes:
        nominal: the asserted amount, in base units.
        tolerance: how far either side still counts as the same amount. Zero means
            exact. This is the claim's own precision, not the provider's.
        asset: what is being counted.
        at_least: the claim asserted a lower bound ("more than 40,000") rather than
            an amount. Then ``nominal`` is the bound and only ``nominal - tolerance``
            upward counts.
    """

    nominal: int = Field(ge=0)
    tolerance: int = Field(default=0, ge=0)
    asset: AssetRef
    at_least: bool = False

    def contains(self, amount: int) -> bool:
        """Whether ``amount`` falls inside the band."""
        if self.at_least:
            return amount >= self.nominal - self.tolerance
        return abs(amount - self.nominal) <= self.tolerance

    @property
    def relative_tolerance(self) -> float:
        """Tolerance as a fraction of the nominal amount.

        ``math.inf`` for a zero nominal amount, because any tolerance around zero
        is proportionally unbounded. Reported rather than clamped: a claim of
        "about 0 BTC" is degenerate and should look degenerate.
        """
        if self.nominal == 0:
            return math.inf if self.tolerance else 0.0
        return self.tolerance / self.nominal

    def scaled(self, factor: float) -> AmountBand:
        """The same band with its tolerance multiplied, for the sensitivity sweep."""
        return self.model_copy(update={"tolerance": max(0, round(self.tolerance * factor))})


class ActivityWindow(LensModel):
    """The time range the claim refers to, with its edges stated explicitly.

    Edge semantics are carried because they change ``k``, the count of the sender's
    transfers: a block at exactly the boundary is either inside or outside, and an
    off-by-one there silently changes the coincidence probability.

    Attributes:
        start: earliest moment included.
        end: latest moment included.
        start_inclusive: whether a transaction exactly at ``start`` counts.
        end_inclusive: whether a transaction exactly at ``end`` counts.
    """

    start: AwareDatetime
    end: AwareDatetime
    start_inclusive: bool = True
    end_inclusive: bool = True

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end < self.start:
            raise ValueError(f"window end {self.end} precedes its start {self.start}")
        return self

    def contains(self, moment: AwareDatetime | None) -> bool:
        """Whether ``moment`` falls inside the window.

        A transaction with no timestamp is **not** inside: unknown is not the same
        as included, and silently counting it would inflate ``k``.
        """
        if moment is None:
            return False
        after_start = moment > self.start or (moment == self.start and self.start_inclusive)
        before_end = moment < self.end or (moment == self.end and self.end_inclusive)
        return after_start and before_end


class ClaimElements(LensModel):
    """The parts of a claim that an analysis can be run against.

    Attributes:
        chain: which chain the claim is about.
        asset: the asset being moved.
        sender: the subject address — the one the claim is *about*. It is the sender unless
            :attr:`received`, which is the case worth reading twice.
        recipient: the address claimed to receive, when the claim names one.
        band: the claimed amount and tolerance, when the claim names one.
        window: the claimed period, when the claim names one.
        received: whether ``sender`` is the address the value came **to**.
        total: whether ``band`` bounds what the subject moved **in total** over the window
            rather than the size of one movement.
    """

    chain: Chain
    asset: AssetRef
    sender: str
    recipient: str | None = None
    band: AmountBand | None = None
    window: ActivityWindow | None = None

    #: Whether ``sender`` is the address the claim says value **came to** rather than went from.
    #:
    #: **The field is named ``received`` and not ``direction``** because it is the one bit the
    #: checkers need, read out of :class:`~chainlens.verify.schema.Claim`'s three-valued
    #: ``direction`` by whoever reduces a claim. `both` is not `received`, and neither is a claim
    #: that names two addresses: with two, the first is the sender and the second the recipient, as
    #: it has always been, and the field stays ``False``.
    #:
    #: **It exists because the library was answering a question nobody asked.** A claim reading
    #: *"N BTC was sent to address X"* names one address, and every filing in the corpus this was
    #: written from uses that phrasing — X was taken for the sender and the check walked X's
    #: *spending*. A wrong verdict, produced silently, on the commonest shape of claim there is.
    received: bool = False

    #: Whether ``band`` bounds a **total** over the window rather than one movement.
    #:
    #: A filing's *"the 3QL Wallet sent approximately 2,138.4 BTC between July 18 and September 30"*
    #: is true of 262 movements and false of every one of them, so the check that reads movements
    #: one at a time refutes it. With this set, the checker adds them up instead. It is stated on
    #: the record and never inferred from the wording, because the sentence is identical either way.
    total: bool = False

    @model_validator(mode="after")
    def _something_to_price(self) -> Self:
        """Refuse a claim with nothing to price.

        A claim naming neither a recipient nor an amount gives a coincidence
        probability of 1 and therefore a likelihood ratio of exactly 1 — no
        evidential weight at all. Reporting that as a number would be the purest
        case of the false precision this module exists to avoid, so the refusal
        happens here rather than being papered over with a weak-looking figure.
        Such a claim still gets a categorical verdict; it just gets no ratio.
        """
        if self.recipient is None and self.band is None:
            raise ValueError(
                "a claim naming neither a recipient nor an amount has nothing to "
                "price: its coincidence probability is 1 and its likelihood ratio "
                "would be exactly 1, which is not evidence. Report a categorical "
                "finding instead of a number."
            )
        return self

    @model_validator(mode="after")
    def _one_chain(self) -> Self:
        """The claim's chain and its asset's chain are the same chain.

        A Bitcoin claim about an ERC-20 token is not a claim that is hard to check,
        it is a claim that does not parse — and letting one exist would put a
        contradiction into the evidence rather than into the parse.
        """
        if self.asset.chain is not self.chain:
            raise ValueError(
                f"claim chain {self.chain.value!r} does not match asset chain "
                f"{self.asset.chain.value!r}"
            )
        return self

    @property
    def priced_elements(self) -> tuple[str, ...]:
        """Which elements the coincidence probability will be computed over.

        Reported alongside the result so a reader can see what the number was
        actually conditioned on — "recipient and amount" and "amount alone" are
        very different claims that produce the same shape of output.
        """
        elements: list[str] = []
        if self.recipient is not None:
            elements.append("recipient")
        if self.band is not None:
            elements.append("amount")
        return tuple(elements)
