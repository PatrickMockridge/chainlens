"""``A holds N`` — a balance claim, which is a claim about *now*.

The subtlety is that a balance is a moving quantity, and the claim is silent about
when. "This wallet holds 40,000 BTC" is checked against what the provider reports at
the moment of the check.

**That the check is of the present is the whole of what this module guarantees, and
it is less than it once claimed.** The docstring here used to say the finding records
the block height it was measured at, and that no adapter supplies one — every
provider returns a bare figure, and the reason string interpolated the missing value
into a sentence that read *"the address held 0 at block None"*. A reason may not name
what the library does not have. What the finding carries now is what is true: the
balance as the provider reported it, and a sentence that says **when** in words a
reader can act on — *at the time of the check*, with the height named only when a
provider actually gave one.

**And a claim about a period that has ended is not answered here at all.** Reading a
present balance to refute a filing's *"20,452 BTC at address X"* answers a question
the claim did not ask: the coins were seized, so the address holds nothing today, and
that says nothing about what it held when the schedule was filed. The honest answer is
a gap, not a verdict — ``UNRESOLVED`` with ``no_data`` and the fix named, which is
what :func:`check_balance` returns for it.

Balances are still the one claim type where the amount is *read*, not inferred: a
provider reporting a balance outside the claimed band is showing the chain's answer,
so the verdict is ``CONTRADICTED`` rather than a shortfall of data.
"""

from __future__ import annotations

from chainlens.exceptions import NotFoundError
from chainlens.models.base import utcnow
from chainlens.models.enums import ClaimVerdict
from chainlens.providers.capabilities import Capability
from chainlens.providers.transport import read_provenance
from chainlens.verify.checks.base import (
    CheckContext,
    Checker,
    CheckOutcome,
    not_reachable,
)
from chainlens.verify.verdicts import ClaimEvidence

__all__ = ["CHECKER", "check_balance"]

METHOD = "balance"


async def check_balance(context: CheckContext) -> CheckOutcome:
    """Compare the claimed holding with the balance the provider reports."""
    provider = context.provider
    elements = context.needs
    holder = elements.sender

    if elements.band is None:
        return CheckOutcome(
            verdict=ClaimVerdict.UNRESOLVED,
            method=METHOD,
            evidence=ClaimEvidence(provider=provider.name, detail={"address": holder}),
            gap=not_reachable(
                "the claim names an address but no amount, so there is no holding to compare"
            ),
        )

    if elements.window is not None and elements.window.end < utcnow():
        # A claim about a period that has ended is not refuted by what the address holds now — the
        # two are answers to different questions, and returning the second under the first's name is
        # the failure this guard exists to prevent. The gap names its fix, because there is one: a
        # provider that can report a holding as of a height.
        return CheckOutcome(
            verdict=ClaimVerdict.UNRESOLVED,
            method=METHOD,
            evidence=ClaimEvidence(provider=provider.name, detail={"address": holder}),
            gap=not_reachable(
                "the claim names a period that has ended, and this check reads the present "
                "balance; what an address held at a past height needs a provider that reports a "
                "holding as of one, which is not configured here"
            ),
        )

    if not provider.supports(Capability.BALANCE):
        return CheckOutcome(
            verdict=ClaimVerdict.UNRESOLVED,
            method=METHOD,
            evidence=ClaimEvidence(provider=provider.name, detail={"address": holder}),
            gap=not_reachable(
                f"provider {provider.name!r} cannot report a balance; a balance claim is "
                "checkable in principle, so this is a gap in the configuration"
            ),
        )

    try:
        balance = await provider.get_balance(holder)
    except NotFoundError:
        return CheckOutcome(
            verdict=ClaimVerdict.UNRESOLVED,
            method=METHOD,
            evidence=ClaimEvidence(provider=provider.name, detail={"address": holder}),
            gap=not_reachable(
                f"provider {provider.name!r} has no record of the address, so what it "
                "holds is not visible from here"
            ),
        )

    observed = balance.amount
    matches = elements.band.contains(observed)
    # **When** the figure was read, in words rather than in a number the library may not have.
    # Naming a height the provider did not return produced "at block None", which reads as a
    # statement about a definite past block and is the opposite of the truth here: the check is of
    # the present. Where a provider does report one, it is named.
    observed_at = (
        f"at block {balance.block_height}"
        if balance.block_height is not None
        else "at the time of the check, which recorded no block height"
    )
    measured_at = {
        "address": holder,
        "observed_balance": observed,
        "claimed_nominal": elements.band.nominal,
        "claimed_tolerance": elements.band.tolerance,
        "block_height": balance.block_height,
    }
    evidence = ClaimEvidence(
        provider=provider.name,
        endpoint="get_balance",
        provenance=(read_provenance(provider.name),),
        detail=measured_at,
    )

    if matches:
        return CheckOutcome(
            verdict=ClaimVerdict.SUPPORTED,
            method=METHOD,
            evidence=evidence,
            assumptions=(f"the balance was read {observed_at}",),
            caveats=(
                "a balance is a moment, not a fact: it was current when it was read and "
                "the claim may describe a different moment",
            ),
        )

    return CheckOutcome(
        verdict=ClaimVerdict.CONTRADICTED,
        method=METHOD,
        evidence=evidence,
        reason=(
            f"the address held {observed} {observed_at}, which is outside the claimed band "
            f"around {elements.band.nominal}"
        ),
        caveats=(
            "the check is of the present balance, and the claim may be about an earlier "
            "moment; what was recorded of when the figure was read is in the evidence, so "
            "the two can be told apart",
        ),
    )


CHECKER = Checker(method=METHOD, run=check_balance, needs_elements=True)
