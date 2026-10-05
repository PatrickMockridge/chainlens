"""``A holds N`` — a balance claim, which is a claim about *now*.

The subtlety is that a balance is a moving quantity, and the claim is silent about
when. "This wallet holds 40,000 BTC" is checked against what the provider reports
at the moment of the check, so the finding records the block height it was measured
at: a contradiction today is not a contradiction of what was true when the post was
written, and without the height there is no way for a reader to tell those apart.

Balances are also the one claim type where the amount is *read*, not inferred. A
provider reporting a balance below the claimed band is showing the chain's answer,
so the verdict is ``CONTRADICTED`` rather than a shortfall of data — with the
measurement height attached, because the claim may simply be older than the check.
"""

from __future__ import annotations

from chainlens.exceptions import NotFoundError
from chainlens.models.base import Provenance, utcnow
from chainlens.models.enums import ClaimVerdict
from chainlens.providers.capabilities import Capability
from chainlens.verify.checks.base import CheckContext, Checker, CheckOutcome
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
            verdict=ClaimVerdict.INSUFFICIENT_DATA,
            method=METHOD,
            evidence=ClaimEvidence(provider=provider.name, detail={"address": holder}),
            reason="the claim names an address but no amount, so there is no holding to compare",
        )

    if not provider.supports(Capability.BALANCE):
        return CheckOutcome(
            verdict=ClaimVerdict.INSUFFICIENT_DATA,
            method=METHOD,
            evidence=ClaimEvidence(provider=provider.name, detail={"address": holder}),
            reason=(
                f"provider {provider.name!r} cannot report a balance; a balance claim is "
                "checkable in principle, so this is a gap in the configuration"
            ),
        )

    try:
        balance = await provider.get_balance(holder)
    except NotFoundError:
        return CheckOutcome(
            verdict=ClaimVerdict.INSUFFICIENT_DATA,
            method=METHOD,
            evidence=ClaimEvidence(provider=provider.name, detail={"address": holder}),
            reason=(
                f"provider {provider.name!r} has no record of the address, so what it "
                "holds is not visible from here"
            ),
        )

    observed = balance.amount
    matches = elements.band.contains(observed)
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
        provenance=(Provenance(provider=provider.name, fetched_at=utcnow()),),
        detail=measured_at,
    )

    if matches:
        return CheckOutcome(
            verdict=ClaimVerdict.SUPPORTED,
            method=METHOD,
            evidence=evidence,
            assumptions=("the balance was read at the height recorded in the evidence",),
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
            f"the address held {observed} at block {balance.block_height}, which is "
            f"outside the claimed band around {elements.band.nominal}"
        ),
        caveats=(
            "the check is of the present balance, and the claim may be about an earlier "
            "moment; the height is recorded so the two can be told apart",
        ),
    )


CHECKER = Checker(method=METHOD, run=check_balance, needs_elements=True)
